import logging

from fastapi import FastAPI, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware

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


app = FastAPI()

origins = [
    "https://calc.cesarsanz.dev",
    "https://energy-calculator-tau.vercel.app",
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
