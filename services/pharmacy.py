from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.pharmacy import Pharmacy
from models.pharmacy_owner import Pharmacy_Owner
from schemas.pharmacy_input_schema import Pharmacy_Input_Schema


async def create_pharmacy(input_for_pharmacy:Pharmacy_Input_Schema,db:Session):
    try:

        owner_from_db=db.query(Pharmacy_Owner).filter(
            Pharmacy_Owner.owner_id==input_for_pharmacy.owner_id
        ).first()
        print(owner_from_db)
        new_pharmacy:Pharmacy=Pharmacy(
            name=input_for_pharmacy.name,
            address=input_for_pharmacy.address,
            pharmacy_owner=owner_from_db
        )
        print(new_pharmacy)

        db.add(new_pharmacy)
        db.commit()
        db.refresh(new_pharmacy)

        return new_pharmacy

    except Exception as e:
        raise HTTPException(status_code=500, detail="DataBase error")
