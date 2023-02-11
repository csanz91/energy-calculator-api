import logging

from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import datetime
import pandas as pd

import tariffs_data
import utils

logger = logging.getLogger()
handler = logging.handlers.RotatingFileHandler(
    "../logs/api.log", mode="a", maxBytes=1024 * 1024 * 10, backupCount=2
)
formatter = logging.Formatter(
    "%(asctime)s <%(levelname).1s> %(funcName)s:%(lineno)s: %(message)s"
)
logger.setLevel(logging.INFO)
handler.setFormatter(formatter)
logger.addHandler(handler)

data_file = "../data/measurements"

app = FastAPI()

origins = [
    "https://calc.cesarsanz.dev",
    "https://energy-calculator-tau.vercel.app",
    "http://localhost:5173",
    "https://gas-calculator-frontend.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/file-upload")
def create_upload_file(file: UploadFile, contracted_p1: float = Form(), contracted_p2: float = Form()):

    assert contracted_p1 and contracted_p2

    rd_10_prices = utils.get_rd_10_prices()
    rd_10_mean_price = utils.get_rd_10_mean_price(rd_10_prices)
    response = {"rd_10_mean_price": rd_10_mean_price, "monthly_data": []}

    df = utils.get_dataframe(file.file)
    for _, month_data in df.groupby([df.Fecha.dt.year, df.Fecha.dt.month]):
        monthly_data = utils.get_data(
            month_data, contracted_p1, contracted_p2, rd_10_mean_price, tariffs_data.tariffs)
        response["monthly_data"].append(monthly_data)

    all_periods_data = utils.get_data(
        df, contracted_p1, contracted_p2, rd_10_mean_price, tariffs_data.tariffs)
    response["all"] = all_periods_data

    return {"response": response}

@app.get("/tariffs")
def get_tariffs():
    return tariffs_data.tariffs


@app.post("/gas-measurement-upload")
def add_measurement(userID: int = Form(1), consumption: float = Form()):

    now = datetime.datetime.now()

    new_data = {"Datetime": now, "Measurement": consumption, "UserID": userID}
    new_df = pd.DataFrame(new_data, index=[now])
    new_df.set_index('Datetime', inplace=True)
    try:
        df: pd.DataFrame = pd.read_pickle(data_file)
        prevValue = df.iloc[-1]["Measurement"]
        if prevValue > consumption:
            raise HTTPException(
                status_code=400, detail=f"Measurement is lower than previous value: {prevValue} m3")
        df = pd.concat([df, new_df])

    except FileNotFoundError:
        df = new_df
        return {}
    finally:
        df.to_pickle(data_file)

    

    # since last measurement
    cost_since_last = utils.calculate_gas_cost(utils.GasDataConsumption(measurement=df.iloc[-2]["Measurement"], time=df.index[-2]),
                                               utils.GasDataConsumption(measurement=df.iloc[-1]["Measurement"], time=df.index[-1]))

    # todays consumption
    todayDayStart = now.replace(hour=0, minute=0, second=0, microsecond=0)
    todayDayEnd = now.replace(hour=23, minute=59, second=59, microsecond=999)
    todays_measurements = df.loc[todayDayStart:todayDayEnd]
    cost_today = utils.calculate_gas_cost(utils.GasDataConsumption(measurement=todays_measurements.iloc[0]["Measurement"], time=todays_measurements.index[0]),
                                          utils.GasDataConsumption(measurement=todays_measurements.iloc[-1]["Measurement"], time=todays_measurements.index[-1]))

    # this week consumptions
    week_start = now.replace(hour=0, minute=0, second=0,
                             microsecond=0) - datetime.timedelta(days=7)
    week_end = now.replace(hour=23, minute=59, second=59, microsecond=999)
    week_measurements = df.loc[week_start:week_end]
    cost_this_week = utils.calculate_gas_cost(utils.GasDataConsumption(measurement=week_measurements.iloc[0]["Measurement"], time=week_measurements.index[0]),
                                              utils.GasDataConsumption(measurement=week_measurements.iloc[-1]["Measurement"], time=week_measurements.index[-1]))

    # this months consumptions
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = now.replace(day=28, hour=23, minute=59,
                            second=59, microsecond=999) + timedelta(days=4)
    month_end = month_end - timedelta(days=month_end.day)
    monthly_measurements = df.loc[month_start:month_end]
    cost_this_month = utils.calculate_gas_cost(utils.GasDataConsumption(measurement=monthly_measurements.iloc[0]["Measurement"], time=monthly_measurements.index[0]),
                                               utils.GasDataConsumption(measurement=monthly_measurements.iloc[-1]["Measurement"], time=monthly_measurements.index[-1]))

    # last month consumptions
    last_month_start = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=30)
    last_month_end = now.replace(
        hour=23, minute=59, second=59, microsecond=999)
    last_monthly_measurements = df.loc[last_month_start:last_month_end]
    cost_last_30days = utils.calculate_gas_cost(utils.GasDataConsumption(measurement=last_monthly_measurements.iloc[0]["Measurement"], time=last_monthly_measurements.index[0]),
                                                utils.GasDataConsumption(measurement=last_monthly_measurements.iloc[-1]["Measurement"], time=last_monthly_measurements.index[-1]))

    return {"cost_since_last": cost_since_last,
            "last_measurement": df.index[-2],
            "cost_today": cost_today,
            "cost_this_week": cost_this_week,
            "cost_this_month": cost_this_month,
            "cost_last_30days": cost_last_30days,
            }
