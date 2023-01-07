import logging
import logging.config
import math
import os
import pickle
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha1
from typing import BinaryIO

import pandas as pd
from holidays_es import Province

logger = logging.getLogger()


def disk_cache(func):
    cache_dir = "cache"
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    def wrapper(*args, **kwargs):
        cache_key = sha1(
            (
                str(func.__module__) + str(func.__name__) +
                str(args) + str(kwargs)
            ).encode("utf-8")
        ).hexdigest()
        cache_path = os.path.join(cache_dir, cache_key)
        if os.path.exists(cache_path):
            modification_time = datetime.fromtimestamp(
                os.path.getmtime(cache_path))
            if modification_time > datetime.now() - timedelta(days=1):
                with open(cache_path, "rb") as f:
                    return pickle.load(f)
        result = func(*args, **kwargs)
        with open(cache_path, "wb") as f:
            pickle.dump(result, f)
        return result

    return wrapper


@disk_cache
def get_rd_10_prices() -> pd.DataFrame:
    rd_10_prices_url = (
        "https://www.mibgas.es/es/file-access/MIBGAS_Data_2022.xlsx?path=AGNO_2022/XLS"
    )
    return pd.read_excel(
        rd_10_prices_url, sheet_name="PGN_RD_10_2022", names=["date", "price"], index_col=0
    )


def get_rd_10_mean_price(rd_10_prices):
    # Get the mean of the last 30 days
    return rd_10_prices.iloc[:30].price.mean() / 1000.0


@dataclass(frozen=True)
class DataConsumption:
    consumption_p1: float  # kWh
    consumption_p2: float  # kWh
    consumption_p3: float  # kWh
    num_days: int

    @property
    def total_consumption(self) -> float:
        return self.consumption_p1 + self.consumption_p2 + self.consumption_p3

    @property
    def p1_distribution(self) -> float:
        return self.consumption_p1 / self.total_consumption * 100.0

    @property
    def p2_distribution(self) -> float:
        return self.consumption_p2 / self.total_consumption * 100.0

    @property
    def p3_distribution(self) -> float:
        return self.consumption_p3 / self.total_consumption * 100.0


@dataclass()
class ElectricityCost:
    energy_cost: float  # €/kWh
    power_cost: float  # €/kWh
    rd_10_cost: float  # €/kWh
    energy_monitor_cost: float  # €/kWh
    social_bonus_cost: float  # €/kWh
    tax_base: float = 0.0  # €
    electricity_cost_tax: float = 0.0  # €
    tax: float = 0.0  # €
    total_cost: float = 0.0  # €

    def __post_init__(self):
        ELECTRICITY_TAX = 0.5  # %
        GENERAL_TAX = 5.0  # %

        electricity_cost = self.cost_without_taxes

        self.electricity_cost_tax = electricity_cost * ELECTRICITY_TAX / 100.0
        self.tax_base = (
            electricity_cost + self.electricity_cost_tax + self.energy_monitor_cost
        )
        self.tax = self.tax_base * GENERAL_TAX / 100.0
        self.total_cost = self.tax_base + self.tax

    @property
    def cost_without_taxes(self) -> float:
        return (
            self.energy_cost
            + self.power_cost
            + self.rd_10_cost
            + self.social_bonus_cost
        )

    def __str__(self) -> str:
        return f"""Energy cost: {self.energy_cost:.2f} € \nPower cost: {self.power_cost:.2f} € \nRD10 cost: {self.rd_10_cost:.2f} € \nEnergy cost: {self.energy_cost:.2f} € \nTotal cost: {self.total_cost:.2f} €"""


@dataclass(frozen=True)
class TariffData:
    name: str
    energy_cost_p1: float  # €/kWh
    energy_cost_p2: float  # €/kWh
    energy_cost_p3: float  # €/kWh
    power_cost_p1: float  # €/kW/day
    power_cost_p2: float  # €/kW/day
    rd_10_included: bool  # The tarrif includes the RD 10 2022 into the prices

    def calculate_electricity_cost(
        self,
        consumption: DataConsumption,
        contracted_p1: float,
        contracted_p2: float,
        rd_10_mean_price: float,
    ) -> ElectricityCost:

        ENERGY_MONITOR_COST_PER_DAY = 0.02663  # €
        SOCIAL_BONUS_COST_PER_DAY = 0.036718  # €

        energy_monitor_cost = consumption.num_days * ENERGY_MONITOR_COST_PER_DAY
        social_bonus_cost = consumption.num_days * SOCIAL_BONUS_COST_PER_DAY

        power_cost = consumption.num_days * (
            self.power_cost_p1 * contracted_p1 + self.power_cost_p2 * contracted_p2
        )

        energy_cost = (
            consumption.consumption_p1 * self.energy_cost_p1
            + consumption.consumption_p2 * self.energy_cost_p2
            + consumption.consumption_p3 * self.energy_cost_p3
        )

        if self.rd_10_included:
            rd_10_cost = 0.0
        else:
            rd_10_cost = consumption.total_consumption * rd_10_mean_price

        return ElectricityCost(
            energy_cost=energy_cost,
            power_cost=power_cost,
            rd_10_cost=rd_10_cost,
            energy_monitor_cost=energy_monitor_cost,
            social_bonus_cost=social_bonus_cost,
        )


def get_dataframe(file: BinaryIO) -> pd.DataFrame:
    """
    Calculates the energy periods consumption.
    Returns:
        DataConsumption instance
    """

    # Read the file
    df = pd.read_csv(filepath_or_buffer=file, sep=";", decimal=",")

    # Parse the column "Fecha" as a datetime object
    df.Fecha = pd.to_datetime(df.Fecha, format="%d/%m/%Y")

    # Get the National Holidays
    df["year"] = pd.DatetimeIndex(df.Fecha).year
    years = df.year.unique()
    holidays = {}
    for year in years:
        year_holidays = Province(name="madrid", year=year)
        holidays[year] = year_holidays.national_holidays()

    # Create a new column indicating if the day is a weekend day or not
    df["weekend"] = df.Fecha.dt.dayofweek // 5 == 1
    # Create a new column indicating if the day was a holiday day or not
    df["holiday"] = df.apply(lambda row: row.Fecha.date()
                             in holidays[row.year], axis=1)

    # Make the hours start from 0
    df.Hora = df.Hora - 1

    return df


def get_periods_consumption(df: pd.DataFrame) -> DataConsumption:

    energyColumn = "Consumo_kWh"
    if energyColumn not in df.columns:
        energyColumn = "AE_kWh"

    # P1 consumption: from 10:00 to 14:00 and from 18:00 to 22:00
    consumption_p1 = df.loc[
        ~df.weekend
        & ~df.holiday
        & ((df.Hora >= 10) & (df.Hora < 14) | (df.Hora >= 18) & (df.Hora < 22))
    ][energyColumn].sum()

    # P2 consumption: from 08:00 to 10:00, from 14:00 to 18:00 and from 22:00 to 24:00
    consumption_p2 = df.loc[
        ~df.weekend
        & ~df.holiday
        & (
            (df.Hora >= 8) & (df.Hora < 10)
            | (df.Hora >= 14) & (df.Hora < 18)
            | (df.Hora >= 22) & (df.Hora < 24)
        )
    ][energyColumn].sum()

    # P3 consumption: from 00:00 to 08:00, weekend days and holidays
    consumption_p3 = df.loc[df.weekend | df.holiday | (df.Hora >= 0) & (df.Hora < 8)][
        energyColumn
    ].sum()

    data = DataConsumption(
        consumption_p1=consumption_p1,
        consumption_p2=consumption_p2,
        consumption_p3=consumption_p3,
        num_days=len(df.groupby("Fecha")),
    )

    # Make sure we have divided the different consumption periods correctly
    assert math.isclose(data.total_consumption, df[energyColumn].sum())

    return data


def get_rd_10_threshold(
    contracted_p1: float,
    contracted_p2: float,
    consumption_data: pd.DataFrame,
    tariffs_costs: list[tuple[str, float]],
    rd_10_mean_price: float,
    tariffs: list[TariffData]
) -> float | None:

    # Get the best tariffs with the RD10 included and not included
    best_rd_tariff = None
    best_non_rd_tariff = None
    for tariff_name, tariff_cost in tariffs_costs:
        for t in tariffs:
            if t.name == tariff_name:
                if t.rd_10_included and not best_rd_tariff:
                    best_rd_tariff = t
                elif not t.rd_10_included and not best_non_rd_tariff:
                    best_non_rd_tariff = t
                break
        if best_rd_tariff and best_non_rd_tariff:
            break

    if best_rd_tariff and best_non_rd_tariff:

        # Get the cost of the best tariffs
        best_rd_10_tariff_cost = best_rd_tariff.calculate_electricity_cost(
            consumption_data, contracted_p1, contracted_p2, rd_10_mean_price
        )
        best_non_rd_10_tariff_cost = best_non_rd_tariff.calculate_electricity_cost(
            consumption_data, contracted_p1, contracted_p2, rd_10_mean_price
        )

        # Calculate the RD10 threshold
        return (
            best_rd_10_tariff_cost.cost_without_taxes
            - best_non_rd_10_tariff_cost.energy_cost
            - best_non_rd_10_tariff_cost.power_cost
        ) / consumption_data.total_consumption


def get_tariffs_costs(
    contracted_p1: float,
    contracted_p2: float,
    consumption_data: pd.DataFrame,
    rd_10_mean_price: float,
    tariffs: list[TariffData]
) -> list[tuple[str, float]]:
    # Get a list with the energy costs for each tariff
    tariffs_costs = [
        (
            t.name,
            t.calculate_electricity_cost(
                consumption_data, contracted_p1, contracted_p2, rd_10_mean_price
            ).total_cost,
        )
        for t in tariffs
    ]
    # Order the tarifs by energy cost
    tariffs_costs.sort(key=lambda x: x[1])

    return tariffs_costs


def get_data(
    df: pd.DataFrame,
    contracted_p1: float,
    contracted_p2: float,
    rd_10_mean_price: float,
    tariffs: list[TariffData]
) -> dict:
    consumption_data = get_periods_consumption(df)

    tariffs_costs = get_tariffs_costs(
        contracted_p1, contracted_p2, consumption_data, rd_10_mean_price, tariffs
    )

    data = {
        "consumption_data": consumption_data.__dict__,
        "tariffs": [],
        "first_day": df.iloc[0].Fecha,
        "last_day": df.iloc[-1].Fecha,
    }
    # Print the results ordered by energy cost
    bestTariffCost = tariffs_costs[0][1]
    for tariff_name, tariff_cost in tariffs_costs:
        tariff_cost_diff = tariff_cost - bestTariffCost
        data["tariffs"].append(
            {"name": tariff_name,
             "tariff_cost": tariff_cost,
             "tariff_cost_diff": tariff_cost_diff})

    th_rd_10_threshold = get_rd_10_threshold(
        contracted_p1, contracted_p2, consumption_data, tariffs_costs, rd_10_mean_price, tariffs
    )
    data["th_rd_10_threshold"] = th_rd_10_threshold

    return data
