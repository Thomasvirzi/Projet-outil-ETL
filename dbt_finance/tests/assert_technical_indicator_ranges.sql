select *
from {{ ref('int_technical_indicators') }}
where rsi_14 not between 0 and 100
   or stochastic_rsi_k not between 0 and 100
   or stochastic_rsi_d not between 0 and 100
   or bollinger_upper_20d < bollinger_lower_20d
   or volatility_20d < 0
   or historical_volatility_20d < 0
   or volume_ratio_20d < 0
