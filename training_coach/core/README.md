# training-coach-core

Decision rules for the running coach: session classification, recovery bands, training load, paces, the race calendar, today's session, and the evening recap.

The Home Assistant add-on still has its own copy of these modules. This package is the one the web app, the Android app, and the API import. A later add-on change can import it and delete the duplicate.

```python
from datetime import date
from coach.engine import plan_from_payload

result = plan_from_payload(
    today=date(2026, 8, 22),
    timezone="Europe/Helsinki",
    recovery={"feel": "good"},
)
print(result.plan.session_type)
```
