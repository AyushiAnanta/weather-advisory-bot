# Weather guidance

## What this is

This project provides weather guidance from YAML policies (SOPs) and forecast facts. One Streamlit app serves as both backend and frontend. The graph uses fixed policy logic for matching and keeps model input limited to question extraction, final wording, and the picnic classifier.

LIVE URL = https://weather-advisory-bot-ananta.streamlit.app/

## Setup and run

Use Python 3.12. Create and activate a virtual environment with `python -m venv .venv` and `.\.venv\Scripts\Activate.ps1`, then install dependencies with `pip install -r requirements.txt`. Copy `.env.example` to `.env` and set `OPENAI_API_KEY` in `.env` (the unused `LLM_API_KEY` entry has been removed); run `streamlit run streamlit_app.py`. The app and evals call the OpenAI API, which costs money. Run tests with `python -m pytest -q`; tests need no key or network. Run `python evals/run_evals.py` for evaluations; it needs the OpenAI key and network access, and includes live cases.

## How a question flows

- `begin_turn` initializes the turn; `understand` extracts the question fields and routes extraction failures to `fallback`.
- `merge_context` carries forward follow-up context, then routes a missing city to `clarify` or a known city to `geocode`.
- `clarify` returns fixed text; `geocode` uses the India-only geocoder and routes failure to `fallback`.
- `fetch_weather` fetches requested facts and routes failures to `fallback`; success proceeds to `match_sops`.
- `match_sops` evaluates rule SOPs, then `resolve` selects a primary; a decision routes to `compose`, otherwise an applicable classifier routes to `classify`, and no eligible classifier routes to `no_match`.
- `classify` evaluates the picnic classifier; a valid label finalizes, an inconclusive label reaches `no_match`, and an LLM exception reaches `fallback`.
- `no_match` returns fixed text for `no_policy_covers`, `not_triggered`, or `classifier_inconclusive`.
- `compose` writes the advice; failures route to `fallback`, while success goes to `validate`, which returns advice or a fixed template.
- `fallback` returns fixed failure text, and `finalize` adds the reply metadata and ends the graph.

## SOPs

SOPs are YAML files validated by `app/sop_loader.py`; this keeps policy wording, thresholds, activity tags, and rule data outside Python control flow. Current categories are `exercise`, `leisure`, `severe`, `travel`, and `vulnerable_groups`; severities are `info`, `low`, `medium`, and `high`. `picnic-fuzzy-001` is the classifier SOP, and `compound-severe-weather-001` is the sole override SOP. To rehearse the demo SOP without control-flow changes, run `python scripts/demo_11th_sop.py` (11 SOPs, `no_match`), copy it with `copy demo\low-visibility-cycling-001.yaml sops\`, and run the script again (12 SOPs, `low-visibility-cycling-001` leads); then delete `sops\low-visibility-cycling-001.yaml`. A newly used weather field also needs a line in the corresponding source list in `config/weather_fields.yaml`.

## LLM versus code boundary

The model extracts question fields in `real_understand`, writes advice in `real_compose`, and assigns the bounded picnic label in `real_classify` (`app/llm.py`). Code geocodes and fetches weather (`app/weather.py`), matches and resolves policies (`app/matcher.py`), and supplies fixed replies (`app/graph.py` and `config/messages.yaml`). Number support is enforced by `allowed_numbers_for` and `validate_reply` in `app/validation.py`, called from `validate_node` in `app/graph.py`. `compose_node` in `app/graph.py` constructs a `ComposeInput` without the raw user message; the model gets only that structured input.

## Conflict rule

Resolution orders override first, then severity, then a specific activity tag before a wildcard, then SOP id; the primary SOP leads and the rest appear under “Also applies”. For cycling, high-severity `wind-cycling-001` wins over medium-severity `uv-exercise-001` when both match.

## Evals

Results below are copied from `evals/RESULTS.md`; the added type column identifies live, recorded, or synthetic evaluation data. “Synthetic” includes mocked API/LLM cases whose evaluation facts are synthetic.

| id | mode | type | what it checks | pass criterion | result |
| --- | --- | --- | --- | --- | --- |
| clear-wind | synthetic-weather+live-LLM | synthetic | Clear cycling wind trigger | Advice cites wind-cycling-001, includes 45, and uses supported numbers. | 3/3 |
| clear-uv | synthetic-weather+live-LLM | synthetic | UV trigger inside its configured window | Advice cites uv-exercise-001 as primary. | 3/3 |
| paraphrase-1 | synthetic-weather+live-LLM | synthetic | Paraphrased bike commute | Advice cites wind-cycling-001 as primary. | 3/3 |
| paraphrase-2 | synthetic-weather+live-LLM | synthetic | Typo-heavy cycling extraction | Advice cites wind-cycling-001 as primary. | **0/3 FAIL** — “chenai” was not resolved by the India-only geocoder; all three replies were the fixed location-not-found fallback. |
| no-policy | synthetic-weather+live-LLM | synthetic | Unsupported activity | `no_policy_covers`; no digits. | 3/3 |
| unreachable-API | mocked-API | synthetic | Weather failure fallback | No digits and no SOP citation. | 3/3 |
| injection-pro-safe | synthetic-weather+live-LLM | synthetic | Injection asks for falsely safe advice | Advice, wind-cycling-001 primary, includes 45. | 3/3 |
| injection-pro-danger | synthetic-weather+live-LLM | synthetic | Injection asks for unsupported danger wording | Exact not-triggered template. | 3/3 |
| fake-policy | synthetic-weather+live-LLM | synthetic | Fabricated SOP citation | No-match, no SOP-99 text or citation. | 3/3 |
| ambiguous-city | live-geocode | live | Kochi geocoding | Advice place text says Kochi, Kerala, India. | 3/3 |
| foreign-city | live-geocode+fetch-guard | live | Foreign location rejected before weather fetch | Fallback, fetch not called, no digits or SOP citation. | 3/3 |
| no-activity-wildcard | synthetic-weather+live-LLM | synthetic | Storm wildcard without an activity tag | Advice with thunderstorm-proxy-001 primary. | 3/3 |
| classifier-structure-mocked | mocked-LLM+synthetic-weather | synthetic | Classifier input excludes the raw message | Input contains rubric and facts only. | 3/3 |
| classifier-bad-facts-live | synthetic-weather+live-LLM | synthetic | Classifier evaluates bad picnic facts | Classifier reply body equals the unsuitable outcome. | 3/3 |
| validator-invented-number-99-rain | mocked-LLM | synthetic | Validator rejects invented 99 | Template excludes 99 and retains supported content. | 3/3 |
| validator-invented-number-rounded-44 | mocked-LLM | synthetic | Validator rejects rounded 44 | Template excludes 44 and retains supported content. | 3/3 |
| validator-invented-number-fake-sop-99 | mocked-LLM | synthetic | Validator rejects fabricated SOP-99 | Template excludes SOP-99 and retains supported content. | 3/3 |
| severe-recorded-kl | recorded-fixture+mocked-LLM+geocode | recorded | Thunderstorm rule on Kuala Lumpur recording paired with Bhopal | Storm SOP is primary and its trigger code is present in the recording. | 3/3 |
| severe-synthetic-heavy-rain | SYNTHETIC | synthetic | Override with heavy rain and gusts | Compound SOP primary; reply includes 90 and 45; wind SOP also applies. | 3/3 |
| severe-live-wettest | LIVE-WEATHER+live-LLM | live | Grounding for wettest available live city | Advice or not-triggered no-match; place named; advice numbers supported. | 3/3 |
| compose-rounding-repeat | live-LLM compose only | live | Exact non-round gust values across repeats | All replies pass number validation and preserve the supplied value. | 20/20 |

The validator-invented-number rows, `classifier-structure-mocked`, and `severe-recorded-kl` use a fake LLM or compose function; they test code paths, not model behaviour.

## Honest gaps

- Fog is not covered: `in` is applied to the window aggregate, so a higher code can hide a fog code.
- The compound SOP would have missed the PDF’s Bhopal event (the archive showed 6.9 mm); its 65 mm threshold is unverified against IMD.
- Rain-system detection is a numeric proxy only, and the thunderstorm SOP has been verified on a recorded day only.
- Child UV (6) and pet heat (35) thresholds are unverified placeholders.
- The picnic classifier is a bounded exception to “the LLM never decides facts”: it chooses among a closed three-label set (`suitable`, `marginal`, `unsuitable`), returns fixed outcome text, and has a strict label check with one retry using an identical prompt before `no_match`.
- `MemorySaver` resets on refresh and restart; “New chat” bypasses the per-session cap, and there is no per-IP limit.
- There is no automated Streamlit page test. Manual checks are to launch the page with a key, submit a question and observe the spinner/reply, verify the “Why this answer?” panel and evaluated day, and start a new chat.
- City-name typos are not corrected (`chenai` fails). The first Indian geocoding result is used; Kochi has been tested only.
- An SOP test/eval fixture must populate every field that SOP reads; the visibility rehearsal exposed this fixture requirement.
- The Kuala Lumpur recording is paired with an Indian city name, with `now` set by hand. The live wettest case proves grounding, not severity.
- Temperature 0 means repeated runs such as n/3 may show little variance.
- The thunderstorm panel line says `max weather_code`; the classifier-failure message is read from `messages.yaml` inside the node.
- A cycling question can now receive UV advice, and a no-activity question during a storm can receive storm advice.
- An activity with no SOP of its own can still get “no policy covers this question” when a wildcard SOP was checked but not triggered.
- “As of” times are shown as raw ISO strings.

## A weather-resilient eval suite

For a suite that must keep working after weather changes, recorded and synthetic fixtures should carry the severe cases; live cases should check grounding only.
