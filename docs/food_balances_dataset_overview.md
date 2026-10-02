# FAOSTAT Food Balances Dataset Overview

## Dataset Summary

- Total rows: 4,820,497
- Time range: 2010 to 2023
- Years available: 14
- Area names: 213
- Countries or territories: 179
- Geographic aggregates: 34
- Food-item names: 120
- Elements: 21
- Units: 7
- Flag values: 3
- Missing values in Value: 0
- Duplicate key groups: 0

## What One Record Represents

A normalized record generally represents one:

**Area x Food Item x Element x Year x Unit**

Examples of elements include production, imports, exports, domestic
supply, losses, food availability, calorie supply, protein supply,
processing, feed, seed, and stock variation.

## Geography Types

| area_type            |   area_count |   total_rows |   first_year |   latest_year |
|:---------------------|-------------:|-------------:|-------------:|--------------:|
| Aggregate            |           34 |       933153 |         2010 |          2023 |
| Country or territory |          179 |      3887344 |         2010 |          2023 |

Country-level analysis should generally exclude FAOSTAT regional
aggregates. In this dataset, area codes of 5000 or greater are treated
as aggregates for initial analytical screening.

## Available Elements

| element                                | unit         |   rows |   areas |   items |
|:---------------------------------------|:-------------|-------:|--------:|--------:|
| Domestic supply quantity               | 1000 t       | 329755 |     213 |     119 |
| Import quantity                        | 1000 t       | 318901 |     213 |     118 |
| Fat supply quantity (t)                | t            | 310269 |     213 |     120 |
| Fat supply quantity (g/capita/day)     | g/cap/d      | 310269 |     213 |     120 |
| Food supply (kcal)                     | million Kcal | 310263 |     213 |     120 |
| Protein supply quantity (t)            | t            | 310263 |     213 |     120 |
| Protein supply quantity (g/capita/day) | g/cap/d      | 310263 |     213 |     120 |
| Food supply (kcal/capita/day)          | kcal/cap/d   | 310263 |     213 |     120 |
| Food supply quantity (kg/capita/yr)    | kg/cap       | 308034 |     213 |     119 |
| Food                                   | 1000 t       | 308034 |     213 |     119 |
| Residuals                              | 1000 t       | 303491 |     213 |     114 |
| Stock Variation                        | 1000 t       | 271538 |     213 |     116 |
| Export quantity                        | 1000 t       | 268537 |     213 |     118 |
| Production                             | 1000 t       | 225994 |     213 |     119 |
| Losses                                 | 1000 t       | 146268 |     213 |     100 |
| Feed                                   | 1000 t       | 114828 |     213 |      98 |
| Other uses (non-food)                  | 1000 t       | 110944 |     213 |     118 |
| Tourist consumption                    | 1000 t       |  93570 |      91 |     105 |
| Processing                             | 1000 t       |  92939 |     213 |      84 |
| Seed                                   | 1000 t       |  63173 |     211 |      58 |
| Total Population - Both sexes          | 1000 No      |   2901 |     213 |       1 |

## FAOSTAT Flags

| flag   |    rows |   percentage |   areas |   items |   first_year |   latest_year |
|:-------|--------:|-------------:|--------:|--------:|-------------:|--------------:|
| E      | 2618688 |      54.324  |     213 |     119 |         2010 |          2023 |
| I      | 2198908 |      45.6158 |     178 |      98 |         2010 |          2023 |
| X      |    2901 |       0.0602 |     213 |       1 |         2010 |          2023 |

Flags must be retained because some values may be official, estimated,
or imputed.

## Column Missingness

| column_name     | column_type   |   null_count |   total_rows |   missing_percentage |
|:----------------|:--------------|-------------:|-------------:|---------------------:|
| Note            | Text          |      4820497 |      4820497 |                  100 |
| Area Code       | Identifier    |            0 |      4820497 |                    0 |
| Area Code (M49) | Identifier    |            0 |      4820497 |                    0 |
| Area            | Text          |            0 |      4820497 |                    0 |
| Item Code       | Identifier    |            0 |      4820497 |                    0 |
| Item Code (FBS) | Identifier    |            0 |      4820497 |                    0 |
| Item            | Text          |            0 |      4820497 |                    0 |
| Element Code    | Identifier    |            0 |      4820497 |                    0 |
| Element         | Text          |            0 |      4820497 |                    0 |
| Year Code       | Identifier    |            0 |      4820497 |                    0 |
| Year            | Year          |            0 |      4820497 |                    0 |
| Unit            | Text          |            0 |      4820497 |                    0 |
| Value           | Numeric       |            0 |      4820497 |                    0 |
| Flag            | Text          |            0 |      4820497 |                    0 |

The Note field is expected to be sparsely populated. Missing values in
individual elements may reflect that the element is not applicable,
not reported, estimated elsewhere, or unavailable.

## Food Items With Loss Data

| item                       |   loss_rows |   areas |   first_year |   latest_year |
|:---------------------------|------------:|--------:|-------------:|--------------:|
| Vegetables, other          |        2901 |     213 |         2010 |          2023 |
| Vegetables                 |        2901 |     213 |         2010 |          2023 |
| Fruits - Excluding Wine    |        2883 |     212 |         2010 |          2023 |
| Starchy Roots              |        2879 |     212 |         2010 |          2023 |
| Fruits, other              |        2879 |     212 |         2010 |          2023 |
| Animal fats                |        2823 |     212 |         2010 |          2023 |
| Offals, Edible             |        2808 |     212 |         2010 |          2023 |
| Offals                     |        2808 |     212 |         2010 |          2023 |
| Fats, Animals, Raw         |        2807 |     212 |         2010 |          2023 |
| Eggs                       |        2849 |     211 |         2010 |          2023 |
| Eggs                       |        2849 |     211 |         2010 |          2023 |
| Oilcrops                   |        2819 |     208 |         2010 |          2023 |
| Cereals - Excluding Beer   |        2819 |     206 |         2010 |          2023 |
| Milk - Excluding Butter    |        2473 |     200 |         2010 |          2023 |
| Milk - Excluding Butter    |        2473 |     200 |         2010 |          2023 |
| Pulses                     |        2708 |     198 |         2010 |          2023 |
| Potatoes and products      |        2700 |     196 |         2010 |          2023 |
| Maize and products         |        2626 |     193 |         2010 |          2023 |
| Tomatoes and products      |        2611 |     191 |         2010 |          2023 |
| Bananas                    |        2409 |     183 |         2010 |          2023 |
| Pulses, Other and products |        2439 |     182 |         2010 |          2023 |
| Onions                     |        2432 |     178 |         2010 |          2023 |
| Sugar Crops                |        2246 |     177 |         2010 |          2023 |
| Wheat and products         |        2389 |     175 |         2010 |          2023 |
| Oranges, Mandarines        |        2344 |     174 |         2010 |          2023 |
| Rice and products          |        2008 |     168 |         2010 |          2023 |
| Treenuts                   |        2141 |     167 |         2010 |          2023 |
| Nuts and products          |        2141 |     167 |         2010 |          2023 |
| Sugar & Sweeteners         |        2153 |     164 |         2010 |          2023 |
| Lemons, Limes and products |        2112 |     160 |         2010 |          2023 |

## Analytical Cautions

1. Aggregate regions and countries must not be added together.
2. Broad food groups may overlap with specific food items.
3. FAOSTAT Losses do not indicate the cause of loss.
4. Recorded losses are not automatically preventable through preservation.
5. Import quantity divided by domestic supply is a useful proxy, not a
   complete measure of consumer import dependence.
6. Values with estimated or imputed flags require sensitivity analysis.
7. Extreme ratios should be reviewed across multiple years.
8. Country comparisons should use consistent units and elements.

## Generated Supporting Files

Detailed CSV profiles are available under:

`outputs/tables/dataset_overview/`
