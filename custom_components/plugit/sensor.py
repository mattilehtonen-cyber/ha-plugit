"""Plugit sensors."""
from __future__ import annotations

from datetime import datetime
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PlugitCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PlugitCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        # Realtime sensors
        PlugitPowerSensor(coordinator, entry),
        PlugitCurrentL1Sensor(coordinator, entry),
        PlugitCurrentL2Sensor(coordinator, entry),
        PlugitCurrentL3Sensor(coordinator, entry),
        PlugitOfferedCurrentSensor(coordinator, entry),
        PlugitVoltageL1Sensor(coordinator, entry),
        PlugitVoltageL2Sensor(coordinator, entry),
        PlugitVoltageL3Sensor(coordinator, entry),
        PlugitSessionEnergySensor(coordinator, entry),
        PlugitPeakPowerSensor(coordinator, entry),
        PlugitSessionStartSensor(coordinator, entry),
        PlugitProblemsSensor(coordinator, entry),
        PlugitStateSensor(coordinator, entry),
        PlugitChargerStatusSensor(coordinator, entry),
        # Monthly stats
        PlugitMonthlyEnergySensor(coordinator, entry),
        PlugitMonthlySessionsSensor(coordinator, entry),
        PlugitMonthlyCO2Sensor(coordinator, entry),
        PlugitMonthlyDurationSensor(coordinator, entry),
        # Leasing refunds
        PlugitCurrentMonthRefundSensor(coordinator, entry),
        PlugitCurrentMonthRefundPriceSensor(coordinator, entry),
        PlugitElectricityPricingSensor(coordinator, entry),
        PlugitFixedElectricityPriceSensor(coordinator, entry),
        PlugitSpotPriceMarginSensor(coordinator, entry),
        PlugitElectricityTaxSensor(coordinator, entry),
        PlugitTransmissionPriceSensor(coordinator, entry),
        PlugitYearlyEnergySensor(coordinator, entry),
        PlugitYearlyRefundSensor(coordinator, entry),
    ])


def _get_meter_value(transaction: dict, measurand: str, phase: str | None = None) -> float | None:
    """Hae uusin mittariarvo timestampin mukaan."""
    matches = [
        mv for mv in transaction.get("latestMeterValues", [])
        if mv["measurand"] == measurand and (phase is None or mv.get("phase") == phase)
    ]
    if not matches:
        return None
    # Ota uusin timestamp
    latest = max(matches, key=lambda m: m.get("timestamp", ""))
    return latest["value"]


class PlugitBaseSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: PlugitCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"plugit_{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Plugit Charger",
            "manufacturer": "Plugit",
        }

    @property
    def device_info(self):
        """Return device information provided by the active transaction."""
        info = dict(self._attr_device_info)
        transaction = self.transaction
        if transaction:
            info["name"] = transaction.get("chargePointName", info["name"])
            info["manufacturer"] = transaction.get("chargePointVendor", info["manufacturer"])
            if model := transaction.get("chargePointModel"):
                info["model"] = model
            if firmware := transaction.get("firmwareVersion"):
                info["sw_version"] = firmware
        return info

    @property
    def transaction(self) -> dict | None:
        return self.coordinator.data.get("transaction")

    @property
    def monthly_stats(self) -> dict | None:
        return self.coordinator.data.get("monthly_stats")

    @property
    def leasing_refunds(self) -> list:
        return self.coordinator.data.get("leasing_refunds", [])

    @property
    def yearly_stats(self) -> list:
        return self.coordinator.data.get("yearly_stats", [])

    @property
    def home_charging_settings(self) -> dict | None:
        return self.coordinator.data.get("home_charging_settings")


# ---- Realtime sensors ----

class PlugitPowerSensor(PlugitBaseSensor):
    _attr_name = "Plugit Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "power")

    @property
    def native_value(self):
        if self.transaction:
            return _get_meter_value(self.transaction, "Power.Active.Import")
        return None


class PlugitCurrentL1Sensor(PlugitBaseSensor):
    _attr_name = "Plugit Current L1"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "current_l1")

    @property
    def native_value(self):
        if self.transaction:
            return _get_meter_value(self.transaction, "Current.Import", "L1")
        return None


class PlugitCurrentL2Sensor(PlugitBaseSensor):
    _attr_name = "Plugit Current L2"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "current_l2")

    @property
    def native_value(self):
        if self.transaction:
            return _get_meter_value(self.transaction, "Current.Import", "L2")
        return None


class PlugitCurrentL3Sensor(PlugitBaseSensor):
    _attr_name = "Plugit Current L3"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "current_l3")

    @property
    def native_value(self):
        if self.transaction:
            return _get_meter_value(self.transaction, "Current.Import", "L3")
        return None


class PlugitOfferedCurrentSensor(PlugitBaseSensor):
    """Maximum current currently offered by the charger."""

    _attr_name = "Plugit Offered Current"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "offered_current")

    @property
    def native_value(self):
        if self.transaction:
            return _get_meter_value(self.transaction, "Current.Offered")
        return None


class PlugitVoltageL1Sensor(PlugitBaseSensor):
    _attr_name = "Plugit Voltage L1"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "voltage_l1")

    @property
    def native_value(self):
        return _get_meter_value(self.transaction, "Voltage", "L1") if self.transaction else None


class PlugitVoltageL2Sensor(PlugitBaseSensor):
    _attr_name = "Plugit Voltage L2"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "voltage_l2")

    @property
    def native_value(self):
        return _get_meter_value(self.transaction, "Voltage", "L2") if self.transaction else None


class PlugitVoltageL3Sensor(PlugitBaseSensor):
    _attr_name = "Plugit Voltage L3"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "voltage_l3")

    @property
    def native_value(self):
        return _get_meter_value(self.transaction, "Voltage", "L3") if self.transaction else None


class PlugitSessionEnergySensor(PlugitBaseSensor):
    _attr_name = "Plugit Session Energy"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "session_energy")

    @property
    def native_value(self):
        if self.transaction:
            try:
                return round(float(self.transaction.get("energy", 0)) / 1000, 3)
            except (ValueError, TypeError):
                return None
        return None


class PlugitPeakPowerSensor(PlugitBaseSensor):
    _attr_name = "Plugit Session Peak Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "session_peak_power")

    @property
    def native_value(self):
        if self.transaction:
            return self.coordinator.data.get("session_peak_power")
        return None


class PlugitSessionStartSensor(PlugitBaseSensor):
    _attr_name = "Plugit Session Start"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "session_start")

    @property
    def native_value(self):
        if not self.transaction or not (timestamp := self.transaction.get("timestampStart")):
            return None
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None


class PlugitProblemsSensor(PlugitBaseSensor):
    _attr_name = "Plugit Charger Problems"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "charger_problems")

    @property
    def native_value(self):
        if not self.transaction:
            return "unknown"
        return "problem" if self.transaction.get("problems") else "clear"

    @property
    def extra_state_attributes(self):
        if not self.transaction:
            return None
        return {"problems": self.transaction.get("problems", [])}


class PlugitStateSensor(PlugitBaseSensor):
    _attr_name = "Plugit State"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "state")

    @property
    def native_value(self):
        if self.transaction:
            return self.transaction.get("state")
        return "idle"


class PlugitChargerStatusSensor(PlugitBaseSensor):
    _attr_name = "Plugit Charger Status"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "charger_status")

    @property
    def native_value(self):
        return self.coordinator.data.get("charger_status", "Unknown")


# ---- Monthly stats sensors ----

class PlugitMonthlyEnergySensor(PlugitBaseSensor):
    _attr_name = "Plugit Monthly Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "monthly_energy")

    @property
    def last_reset(self):
        from datetime import datetime
        now = datetime.now()
        return datetime(now.year, now.month, 1)

    @property
    def native_value(self):
        if self.monthly_stats:
            try:
                return round(self.monthly_stats["totals"]["energy"] / 1000, 2)
            except (KeyError, TypeError):
                return None
        return None


class PlugitMonthlySessionsSensor(PlugitBaseSensor):
    _attr_name = "Plugit Monthly Sessions"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "sessions"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "monthly_sessions")

    @property
    def native_value(self):
        if self.monthly_stats:
            return self.monthly_stats.get("transactionCount")
        return None


class PlugitMonthlyCO2Sensor(PlugitBaseSensor):
    _attr_name = "Plugit Monthly CO2 Savings"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kg"
    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "monthly_co2")

    @property
    def native_value(self):
        if self.monthly_stats:
            try:
                return round(self.monthly_stats["totals"]["co2Savings"]["total"], 2)
            except (KeyError, TypeError):
                return None
        return None


class PlugitMonthlyDurationSensor(PlugitBaseSensor):
    _attr_name = "Plugit Monthly Charging Time"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "h"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "monthly_duration")

    @property
    def native_value(self):
        if self.monthly_stats:
            try:
                return round(self.monthly_stats["totals"]["duration"] / 3600, 1)
            except (KeyError, TypeError):
                return None
        return None


# ---- Leasing refund sensors ----

class PlugitCurrentMonthRefundSensor(PlugitBaseSensor):
    _attr_name = "Plugit Monthly Refund"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "monthly_refund")

    @property
    def native_value(self):
        if not self.leasing_refunds:
            return None
        now = datetime.now()
        for refund in self.leasing_refunds:
            month = refund.get("activeMonth", "")
            if f"{now.year}-{now.month:02d}" in month:
                return round(refund.get("compensationPrice", 0), 2)
        return None


class PlugitCurrentMonthRefundPriceSensor(PlugitBaseSensor):
    _attr_name = "Plugit Refund Price"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "refund_price")

    @property
    def native_value(self):
        if not self.leasing_refunds:
            return None
        now = datetime.now()
        for refund in self.leasing_refunds:
            month = refund.get("activeMonth", "")
            if f"{now.year}-{now.month:02d}" in month:
                return round(refund.get("averageEnergyPrice", 0) / 100, 4)
        return None


class PlugitElectricityPricingSensor(PlugitBaseSensor):
    _attr_name = "Plugit Electricity Pricing"
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "electricity_pricing")

    @property
    def native_value(self):
        settings = self.home_charging_settings
        if not settings:
            return None
        return "spot" if settings.get("spotPricing", {}).get("active") else "fixed"

    @property
    def extra_state_attributes(self):
        settings = self.home_charging_settings
        if not settings:
            return None
        return {"spot_price_interval": settings.get("spotPricing", {}).get("mtu")}


class PlugitFixedElectricityPriceSensor(PlugitBaseSensor):
    _attr_name = "Plugit Fixed Electricity Price"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "c/kWh"
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "fixed_electricity_price")

    @property
    def native_value(self):
        if self.home_charging_settings:
            return self.home_charging_settings.get("kwhPrice", 0)
        return None


class PlugitSpotPriceMarginSensor(PlugitBaseSensor):
    _attr_name = "Plugit Spot Price Margin"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "c/kWh"
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "spot_price_margin")

    @property
    def native_value(self):
        settings = self.home_charging_settings
        if settings:
            return settings.get("spotPricing", {}).get("margin", 0)
        return None


class PlugitElectricityTaxSensor(PlugitBaseSensor):
    _attr_name = "Plugit Electricity Tax"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "c/kWh"
    _attr_icon = "mdi:receipt-text"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "electricity_tax")

    @property
    def native_value(self):
        if self.home_charging_settings:
            return self.home_charging_settings.get("electricityTax", 0)
        return None


class PlugitTransmissionPriceSensor(PlugitBaseSensor):
    _attr_name = "Plugit Transmission Price"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "c/kWh"
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "transmission_price")

    @property
    def native_value(self):
        settings = self.home_charging_settings
        if settings:
            transmission = settings.get("transmission", {})
            return transmission.get("staticPrice", 0)
        return None


class PlugitYearlyEnergySensor(PlugitBaseSensor):
    _attr_name = "Plugit Yearly Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "yearly_energy")

    @property
    def last_reset(self):
        from datetime import datetime
        now = datetime.now()
        return datetime(now.year, 1, 1)

    @property
    def native_value(self):
        if not self.yearly_stats:
            return None
        total = sum(m.get("totals", {}).get("energy", 0) for m in self.yearly_stats)
        return round(total / 1000, 2)


class PlugitYearlyRefundSensor(PlugitBaseSensor):
    _attr_name = "Plugit Yearly Refund"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "yearly_refund")

    @property
    def native_value(self):
        if not self.leasing_refunds:
            return None
        now = datetime.now()
        total = sum(
            r.get("compensationPrice", 0)
            for r in self.leasing_refunds
            if str(now.year) in r.get("activeMonth", "")
        )
        return round(total, 2)
