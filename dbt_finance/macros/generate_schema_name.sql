{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name == 'marts' -%}
        {{ var('mart_dataset', 'mart') }}
    {%- elif custom_schema_name is not none -%}
        {{ target.schema }}
    {%- else -%}
        {{ target.schema }}
    {%- endif -%}
{%- endmacro %}
