{{ config(
    partition_by={"field": "date", "data_type": "date"},
    cluster_by=["symbol"]
) }}

with prices as (
    select
        commodity_id,
        commodity_name,
        symbol,
        category,
        date,
        open,
        high,
        low,
        close,
        adjusted_close,
        volume,
        lag(close) over (partition by symbol order by date) as previous_close,
        row_number() over (partition by symbol order by date) as row_number_symbol
    from {{ ref('int_tradable_assets') }}
),

returns as (
    select
        *,
        safe_divide(close - previous_close, previous_close) as simple_return,
        case
            when close > 0 and previous_close > 0 then ln(safe_divide(close, previous_close))
        end as log_return,
        avg(close) over (
            partition by symbol
            order by date
            rows between 19 preceding and current row
        ) as sma_20,
        avg(close) over (
            partition by symbol
            order by date
            rows between 49 preceding and current row
        ) as sma_50,
        avg(close) over (
            partition by symbol
            order by date
            rows between 99 preceding and current row
        ) as sma_100,
        avg(close) over (
            partition by symbol
            order by date
            rows between 199 preceding and current row
        ) as sma_200,
        stddev_samp(close) over (
            partition by symbol
            order by date
            rows between 19 preceding and current row
        ) as close_stddev_20d,
        avg(volume) over (
            partition by symbol
            order by date
            rows between 19 preceding and current row
        ) as volume_avg_20d,
        stddev_samp(safe_divide(close - previous_close, previous_close)) over (
            partition by symbol
            order by date
            rows between 19 preceding and current row
        ) as volatility_20d,
        greatest(
            high - low,
            abs(high - coalesce(previous_close, close)),
            abs(low - coalesce(previous_close, close))
        ) as true_range
    from prices
),

rsi_inputs as (
    select
        *,
        greatest(close - previous_close, 0) as gain,
        greatest(previous_close - close, 0) as loss
    from returns
),

averaged_indicators as (
    select
        *,
        avg(true_range) over (
            partition by symbol
            order by date
            rows between 13 preceding and current row
        ) as atr_14,
        avg(gain) over (
            partition by symbol
            order by date
            rows between 13 preceding and current row
        ) as avg_gain_14,
        avg(loss) over (
            partition by symbol
            order by date
            rows between 13 preceding and current row
        ) as avg_loss_14
    from rsi_inputs
),

rsi_indicators as (
    select
        *,
        case
            when avg_loss_14 = 0 and avg_gain_14 > 0 then 100
            when avg_loss_14 = 0 and avg_gain_14 = 0 then 50
            else 100 - (100 / (1 + safe_divide(avg_gain_14, avg_loss_14)))
        end as rsi_14
    from averaged_indicators
),

stochastic_inputs as (
    select
        *,
        min(rsi_14) over (
            partition by symbol
            order by date
            rows between 13 preceding and current row
        ) as rsi_min_14,
        max(rsi_14) over (
            partition by symbol
            order by date
            rows between 13 preceding and current row
        ) as rsi_max_14
    from rsi_indicators
),

stochastic_k as (
    select
        *,
        case
            when rsi_max_14 = rsi_min_14 then 50
            else 100 * safe_divide(rsi_14 - rsi_min_14, rsi_max_14 - rsi_min_14)
        end as stochastic_rsi_k
    from stochastic_inputs
),

stochastic_d as (
    select
        *,
        avg(stochastic_rsi_k) over (
            partition by symbol
            order by date
            rows between 2 preceding and current row
        ) as stochastic_rsi_d
    from stochastic_k
),

ema_values as (
    select
        current_row.symbol,
        current_row.date,
        safe_divide(
            sum(
                history_row.close
                * (2.0 / (12 + 1))
                * pow(1 - (2.0 / (12 + 1)), current_row.row_number_symbol - history_row.row_number_symbol)
            ),
            sum(
                (2.0 / (12 + 1))
                * pow(1 - (2.0 / (12 + 1)), current_row.row_number_symbol - history_row.row_number_symbol)
            )
        ) as ema_12,
        safe_divide(
            sum(
                history_row.close
                * (2.0 / (26 + 1))
                * pow(1 - (2.0 / (26 + 1)), current_row.row_number_symbol - history_row.row_number_symbol)
            ),
            sum(
                (2.0 / (26 + 1))
                * pow(1 - (2.0 / (26 + 1)), current_row.row_number_symbol - history_row.row_number_symbol)
            )
        ) as ema_26
    from stochastic_d as current_row
    inner join stochastic_d as history_row
        on current_row.symbol = history_row.symbol
       and history_row.row_number_symbol between current_row.row_number_symbol - 120 and current_row.row_number_symbol
    group by current_row.symbol, current_row.date
),

macd_values as (
    select
        stochastic_d.*,
        ema_values.ema_12,
        ema_values.ema_26,
        ema_values.ema_12 - ema_values.ema_26 as macd
    from stochastic_d
    inner join ema_values
        on stochastic_d.symbol = ema_values.symbol
       and stochastic_d.date = ema_values.date
),

macd_signal_values as (
    select
        current_row.symbol,
        current_row.date,
        safe_divide(
            sum(
                history_row.macd
                * (2.0 / (9 + 1))
                * pow(1 - (2.0 / (9 + 1)), current_row.row_number_symbol - history_row.row_number_symbol)
            ),
            sum(
                (2.0 / (9 + 1))
                * pow(1 - (2.0 / (9 + 1)), current_row.row_number_symbol - history_row.row_number_symbol)
            )
        ) as macd_signal
    from macd_values as current_row
    inner join macd_values as history_row
        on current_row.symbol = history_row.symbol
       and history_row.row_number_symbol between current_row.row_number_symbol - 45 and current_row.row_number_symbol
    group by current_row.symbol, current_row.date
),

final_indicators as (
    select
        macd_values.*,
        macd_signal_values.macd_signal
    from macd_values
    inner join macd_signal_values
        on macd_values.symbol = macd_signal_values.symbol
       and macd_values.date = macd_signal_values.date
)

select
    commodity_id,
    commodity_name,
    symbol,
    category,
    date,
    open,
    high,
    low,
    close,
    adjusted_close,
    volume,
    simple_return,
    log_return,
    sma_20,
    sma_50,
    sma_100,
    sma_200,
    sma_20 + (2 * close_stddev_20d) as bollinger_upper_20d,
    sma_20 - (2 * close_stddev_20d) as bollinger_lower_20d,
    safe_divide(volume, volume_avg_20d) as volume_ratio_20d,
    rsi_14,
    stochastic_rsi_k,
    stochastic_rsi_d,
    ema_12,
    ema_26,
    macd,
    macd_signal,
    macd - macd_signal as macd_histogram,
    atr_14,
    volatility_20d,
    volatility_20d * sqrt(252) as historical_volatility_20d
from final_indicators
