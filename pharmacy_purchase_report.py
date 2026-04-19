from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class PharmacyPurchaseReport(Base):
    __tablename__ = "pharmacy_sales_reports"

    id = Column(Integer, primary_key=True, index=True)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id"))
    report_date = Column(String)
    total_sales = Column(Integer)
    total_items_sold = Column(Integer)
    pharmacy = relationship("Pharmacy", back_populates="reports")
