from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class ScreenshotResult(Base):
    __tablename__ = "screenshot_results"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True)
    screenshot_path = Column(String)
    original_screenshot_path = Column(String, nullable=True)
    status = Column(String) # Added status field
    ads_found = Column(Integer, nullable=True)
    matches_found = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    matched_creative_name = Column(String, nullable=True)
    matched_creative_size = Column(String, nullable=True)
    injection_type = Column(String, nullable=True)
    device = Column(String, default="Desktop")

