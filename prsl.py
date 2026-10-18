"""PRSL (Predictive Remaining Shelf-Life) decay logic.

Simplified Arrhenius / Q10 rule: the crop's degradation rate doubles for every
10 degC above the optimal storage temperature.
"""

OPTIMAL_TEMP_C = 4.0

# Room status thresholds (degC)
WARNING_ABOVE_C = 8.0
FAILING_ABOVE_C = 15.0


def calculate_decay_multiplier(current_temp_c, optimal_temp_c=OPTIMAL_TEMP_C):
    """Q10 temperature coefficient.

    Returns how many hours of shelf life are lost per real hour.
    At or below the optimal temperature the rate is normal (1.0x).
    A tomato at 24 degC decays 4x faster: 1 hour in reality costs 4 hours of shelf life.
    """
    if current_temp_c <= optimal_temp_c:
        return 1.0
    delta_t = current_temp_c - optimal_temp_c
    return 2 ** (delta_t / 10.0)


def classify(temp_c):
    """Map a temperature reading to a room status: good / warning / failing."""
    if temp_c > FAILING_ABOVE_C:
        return "failing"
    if temp_c > WARNING_ABOVE_C:
        return "warning"
    return "good"


def apply_decay(current_shelf_life_h, temp_c, elapsed_sim_hours):
    """Return (new_shelf_life, multiplier) after `elapsed_sim_hours` at `temp_c`."""
    mult = calculate_decay_multiplier(temp_c)
    return max(0.0, current_shelf_life_h - elapsed_sim_hours * mult), mult


if __name__ == "__main__":
    print("Temp (C) | Decay multiplier | Shelf-life lost per 1 h")
    for t in (4, 10, 14, 24, 30, 34):
        m = calculate_decay_multiplier(t)
        print(f"{t:8} | {m:16.2f}x | {m:.2f} h")
