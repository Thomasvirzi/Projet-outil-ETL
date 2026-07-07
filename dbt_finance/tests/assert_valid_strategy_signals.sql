select *
from {{ ref('int_strategy_signals') }}
where signal not in (-1, 0, 1)
   or signal is null
