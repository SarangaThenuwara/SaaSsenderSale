import os
from dotenv import load_dotenv

load_dotenv()
from app.assigner import assign_pending_recipients
import logging
logging.basicConfig(level=logging.INFO)

print("Running user recipient assignments...")
res = assign_pending_recipients()
print(f"Assigner response: {res}")
