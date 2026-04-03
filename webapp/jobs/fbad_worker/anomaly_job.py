import os
import sys
import logging
import calendar
from datetime import date, timedelta, datetime

from db.database import get_db_cursor
from crud import costs as costs_crud
from services import cost_service
from jobs.fbad_worker.forecast_model import ForecastModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def run_anomaly_job():
    """Run the Forecast-Based Anomaly Detection job"""
    logger.info("Starting FBAD worker")
    
    # Initialize DB connection
    cursor_generator = get_db_cursor()
    cursor = next(cursor_generator)
    
    try:
        today = date.today()
        base_date = today.replace(day=1)
        start_date = base_date
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)
        
        # Pull 35 days prior + current month
        history_start = start_date - timedelta(days=35)
        
        # Identify active scopes with a budget
        scopes = costs_crud.get_active_budgets_scopes(cursor, base_date)
        if not scopes:
            logger.info("No active budgets found. Exiting.")
            return
            
        logger.info(f"Found {len(scopes)} budget scopes to evaluate.")
        
        # Initialize Forecast Model
        model = ForecastModel(season_length=7, min_data_points=14)
        
        # Determine actual cutoff date
        max_date_row = costs_crud.get_max_date(cursor, history_start, end_date)
        if max_date_row and max_date_row[0]:
            cutoff_date_obj = max_date_row[0]
            if isinstance(cutoff_date_obj, datetime):
                cutoff_date_obj = cutoff_date_obj.date()
                
            safe_max_date = date.today() - timedelta(days=3) 
            if cutoff_date_obj > safe_max_date:
                cutoff_date_obj = safe_max_date
                
            cutoff_day = cutoff_date_obj.day
        else:
            cutoff_date_obj = date.today() - timedelta(days=3)
            cutoff_day = 0
            
        for s in scopes:
            scope_id = s["scope_id"]
            tags = s["tags"]
            logger.info(f"Processing Scope: {scope_id}, Tags: {tags}")
            
            # Fetch Aggregated Daily Costs
            cost_dict = cost_service.get_aggregated_daily_costs(
                cursor, scope_id, tags, start_date=history_start, end_date=end_date
            )
            
            # Format to ML dataset
            df_data = []
            first_nonzero_date = history_start
            if cost_dict:
                for d_str in sorted(cost_dict.keys()):
                    if cost_dict[d_str] > 0.0:
                        first_nonzero_date = date.fromisoformat(d_str)
                        break
                        
            curr_date = max(history_start, first_nonzero_date)
            
            actual_cumulative_sum = 0.0
            
            # Read all historical values up to cutoff
            while curr_date <= cutoff_date_obj:
                d_str = curr_date.isoformat()
                val = cost_dict.get(d_str, 0.0)
                df_data.append({
                    "ds": curr_date,
                    "y": val, 
                    "unique_id": f"scope_{scope_id}"
                })
                
                # Sum actuals for the current month only
                if curr_date >= base_date:
                    actual_cumulative_sum += val
                    
                curr_date += timedelta(days=1)
                
            # Run the model
            days_to_predict = (end_date - cutoff_date_obj).days if df_data else 0
            results = model.process(df_data, days_to_predict, cutoff_date_obj)
            
            future_forecast_sum = sum(results["future_forecasts"].values())
            projected_total = actual_cumulative_sum + future_forecast_sum
            
            anomalies = results["anomalies"]
            
            # Save calculations back to database
            if projected_total > 0:
                costs_crud.save_forecast_snapshot(
                    cursor, 
                    scope_id, 
                    tags, 
                    base_date, 
                    round(projected_total, 2), 
                    daily_forecasts=results["future_forecasts"]
                )
                
            if anomalies:
                costs_crud.save_anomalies(cursor, scope_id, tags, anomalies)
                logger.info(f"Saved {len(anomalies)} anomalies for scope {scope_id}.")
            else:
                logger.info(f"No anomalies found for scope {scope_id}.")
                
            # Commit processing per scope
            cursor.connection.commit()
            
    except Exception as e:
        logger.error(f"Worker failed: {e}", exc_info=True)
        cursor.connection.rollback()
    finally:
        # Generator cleanup
        try:
            cursor.connection.close()
        except:
            pass

if __name__ == "__main__":
    run_anomaly_job()
