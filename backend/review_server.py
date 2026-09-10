"""Optional local QA server. Never changes the OS clock or production database.

Run: python -m backend.review_server
Set simulated lab time in .qa/clock.txt, then refresh the browser on port 8001.
"""
import os
from datetime import datetime
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / '.qa'
QA.mkdir(exist_ok=True)
CLOCK = QA / 'clock.txt'
if not CLOCK.exists():
    CLOCK.write_text('2026-09-21T09:00', encoding='utf-8')
# Override before importing the API, whose initialization opens its database.
os.environ['FLYKEEPER_DB'] = str(QA / 'time-review.db')
from . import app as module  # noqa: E402

def simulated_now(db):
    value = datetime.fromisoformat(CLOCK.read_text(encoding='utf-8-sig').strip())
    if value.tzinfo is not None:
        raise ValueError('QA clock must be laboratory-local without a UTC offset')
    return value

module.now_of = simulated_now

if __name__ == '__main__':
    uvicorn.run(module.app, host='127.0.0.1', port=8001)
