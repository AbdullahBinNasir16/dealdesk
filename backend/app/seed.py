"""Demo data: 4 dealers (2 real-estate agencies, 2 car dealers) and their inventory.

Run automatically on startup when the listings table is empty.
"""
import os

from sqlalchemy import func, insert, select

from .auth import hash_password
from .db import agencies, engine, listings, now

AGENCIES = [
    # id, name, kind, city, phone, username, default password
    ("skyline", "Skyline Estates", "property", "Lahore", "042-111-759-463", "skyline", "skyline123"),
    ("capital", "Capital Homes", "property", "Islamabad", "051-111-227-482", "capital", "capital123"),
    ("prime", "Prime Motors", "car", "Lahore", "042-111-774-631", "prime", "prime123"),
    ("autohub", "AutoHub Karachi", "car", "Karachi", "021-111-288-648", "autohub", "autohub123"),
]

L, CR = 100_000, 10_000_000  # 1 lakh, 1 crore

PROPERTIES = [
    # id, agency, subtype, title, city, area, price, specs
    ("P-101", "skyline", "plot", "1 Kanal Residential Plot, DHA Phase 5", "Lahore", "DHA Phase 5", int(2.75 * CR),
     {"size": "1 kanal", "possession": "yes", "facing": "park"}),
    ("P-102", "skyline", "plot", "10 Marla Plot, DHA Phase 5 Block L", "Lahore", "DHA Phase 5", int(1.9 * CR),
     {"size": "10 marla", "possession": "yes"}),
    ("P-103", "skyline", "house", "1 Kanal Modern House, DHA Phase 5", "Lahore", "DHA Phase 5", int(7.5 * CR),
     {"size": "1 kanal", "beds": 5, "baths": 6, "furnished": "semi"}),
    ("P-104", "skyline", "house", "10 Marla Brand New House, DHA Phase 6", "Lahore", "DHA Phase 6", int(4.6 * CR),
     {"size": "10 marla", "beds": 4, "baths": 5}),
    ("P-105", "skyline", "plot", "1 Kanal Plot, DHA Phase 7 (Investment)", "Lahore", "DHA Phase 7", int(1.65 * CR),
     {"size": "1 kanal", "possession": "no"}),
    ("P-106", "skyline", "plot", "5 Marla Plot, Bahria Town Lahore (Sector E)", "Lahore", "Bahria Town", 48 * L,
     {"size": "5 marla", "possession": "yes"}),
    ("P-107", "skyline", "plot", "10 Marla Plot, Bahria Town Lahore (Jasmine Block)", "Lahore", "Bahria Town", 95 * L,
     {"size": "10 marla", "possession": "yes"}),
    ("P-108", "skyline", "house", "5 Marla House, Bahria Town Lahore", "Lahore", "Bahria Town", int(1.85 * CR),
     {"size": "5 marla", "beds": 3, "baths": 4}),
    ("P-109", "skyline", "apartment", "2 Bed Apartment, Gulberg III", "Lahore", "Gulberg", int(1.4 * CR),
     {"size": "1,250 sq ft", "beds": 2, "baths": 2, "floor": 6}),
    ("P-110", "skyline", "house", "10 Marla House, Johar Town", "Lahore", "Johar Town", int(3.2 * CR),
     {"size": "10 marla", "beds": 5, "baths": 5}),
    ("P-111", "skyline", "commercial", "4 Marla Commercial Plot, DHA Phase 6 CCA", "Lahore", "DHA Phase 6", int(6.8 * CR),
     {"size": "4 marla", "use": "commercial"}),
    ("P-112", "skyline", "apartment", "1 Bed Apartment, Bahria Town Lahore", "Lahore", "Bahria Town", 72 * L,
     {"size": "650 sq ft", "beds": 1, "baths": 1, "rental_yield": "7%"}),
    ("P-201", "capital", "plot", "10 Marla Plot, Bahria Town Phase 8", "Islamabad", "Bahria Town Phase 8", 85 * L,
     {"size": "10 marla", "possession": "yes"}),
    ("P-202", "capital", "plot", "1 Kanal Plot, Bahria Town Phase 8", "Islamabad", "Bahria Town Phase 8", int(1.9 * CR),
     {"size": "1 kanal", "possession": "yes"}),
    ("P-203", "capital", "house", "7 Marla House, Bahria Town Phase 7", "Islamabad", "Bahria Town Phase 7", int(2.6 * CR),
     {"size": "7 marla", "beds": 4, "baths": 4}),
    ("P-204", "capital", "plot", "1 Kanal Plot, DHA Phase 2 Islamabad", "Islamabad", "DHA Phase 2", int(4.1 * CR),
     {"size": "1 kanal", "possession": "yes"}),
    ("P-205", "capital", "apartment", "3 Bed Apartment, E-11", "Islamabad", "E-11", int(2.3 * CR),
     {"size": "1,850 sq ft", "beds": 3, "baths": 3}),
    ("P-206", "capital", "house", "1 Kanal House, F-7", "Islamabad", "F-7", int(19.5 * CR),
     {"size": "1 kanal", "beds": 6, "baths": 7}),
    ("P-207", "capital", "plot", "8 Marla Plot, G-13", "Islamabad", "G-13", int(2.2 * CR),
     {"size": "8 marla", "possession": "yes"}),
    ("P-208", "capital", "plot", "5 Marla Plot, Gulberg Greens", "Islamabad", "Gulberg Greens", 62 * L,
     {"size": "5 marla", "possession": "no"}),
    ("P-209", "capital", "apartment", "2 Bed Apartment, Bahria Enclave", "Islamabad", "Bahria Enclave", 98 * L,
     {"size": "1,100 sq ft", "beds": 2, "baths": 2}),
    ("P-210", "capital", "house", "10 Marla House, DHA Phase 2 Islamabad", "Islamabad", "DHA Phase 2", int(5.4 * CR),
     {"size": "10 marla", "beds": 5, "baths": 6}),
]

CARS = [
    # id, agency, subtype, make, model, title, year, city, area, price, specs
    ("C-301", "prime", "sedan", "Toyota", "Corolla", "Toyota Corolla GLi 1.3 2019", 2019, "Lahore", "Prime Motors, Gulberg", 46 * L,
     {"mileage_km": 68000, "transmission": "manual", "fuel": "petrol", "color": "white"}),
    ("C-302", "prime", "sedan", "Toyota", "Corolla", "Toyota Corolla Altis 1.6 2020", 2020, "Lahore", "Prime Motors, Gulberg", 54 * L,
     {"mileage_km": 52000, "transmission": "automatic", "fuel": "petrol", "color": "silver"}),
    ("C-303", "prime", "sedan", "Toyota", "Corolla", "Toyota Corolla Altis X 1.6 2022", 2022, "Lahore", "Prime Motors, Gulberg", int(59.5 * L),
     {"mileage_km": 21000, "transmission": "automatic", "fuel": "petrol", "color": "black"}),
    ("C-304", "prime", "sedan", "Toyota", "Corolla", "Toyota Corolla Altis Grande 1.8 2021", 2021, "Lahore", "Prime Motors, Gulberg", 63 * L,
     {"mileage_km": 39000, "transmission": "automatic", "fuel": "petrol", "color": "grey"}),
    ("C-305", "prime", "sedan", "Honda", "Civic", "Honda Civic Oriel 1.5 Turbo 2021", 2021, "Lahore", "Prime Motors, Gulberg", 78 * L,
     {"mileage_km": 34000, "transmission": "automatic", "fuel": "petrol", "color": "white"}),
    ("C-306", "prime", "sedan", "Honda", "Civic", "Honda Civic RS 2023", 2023, "Lahore", "Prime Motors, Gulberg", int(1.02 * CR),
     {"mileage_km": 9000, "transmission": "automatic", "fuel": "petrol", "color": "red"}),
    ("C-307", "prime", "sedan", "Honda", "City", "Honda City 1.5 Aspire 2022", 2022, "Lahore", "Prime Motors, Gulberg", 49 * L,
     {"mileage_km": 26000, "transmission": "automatic", "fuel": "petrol", "color": "white"}),
    ("C-308", "prime", "hatchback", "Suzuki", "Alto", "Suzuki Alto VXL AGS 2023", 2023, "Lahore", "Prime Motors, Gulberg", 29 * L,
     {"mileage_km": 12000, "transmission": "automatic", "fuel": "petrol", "color": "silver"}),
    ("C-309", "prime", "hatchback", "Suzuki", "Swift", "Suzuki Swift GLX CVT 2023", 2023, "Lahore", "Prime Motors, Gulberg", 45 * L,
     {"mileage_km": 15000, "transmission": "automatic", "fuel": "petrol", "color": "blue"}),
    ("C-310", "prime", "suv", "KIA", "Sportage", "KIA Sportage AWD 2022", 2022, "Lahore", "Prime Motors, Gulberg", int(84 * L),
     {"mileage_km": 30000, "transmission": "automatic", "fuel": "petrol", "color": "white"}),
    ("C-311", "prime", "suv", "Toyota", "Fortuner", "Toyota Fortuner Legender 2022", 2022, "Lahore", "Prime Motors, Gulberg", int(1.65 * CR),
     {"mileage_km": 28000, "transmission": "automatic", "fuel": "diesel", "color": "white"}),
    ("C-312", "prime", "suv", "Haval", "H6", "Haval H6 HEV 2024", 2024, "Lahore", "Prime Motors, Gulberg", int(1.08 * CR),
     {"mileage_km": 6000, "transmission": "automatic", "fuel": "hybrid", "color": "grey"}),
    ("C-401", "autohub", "sedan", "Toyota", "Corolla", "Toyota Corolla Altis 1.6 2021", 2021, "Karachi", "AutoHub, Shahrah-e-Faisal", 57 * L,
     {"mileage_km": 41000, "transmission": "automatic", "fuel": "petrol", "color": "white"}),
    ("C-402", "autohub", "sedan", "Toyota", "Yaris", "Toyota Yaris ATIV X CVT 1.5 2022", 2022, "Karachi", "AutoHub, Shahrah-e-Faisal", 47 * L,
     {"mileage_km": 24000, "transmission": "automatic", "fuel": "petrol", "color": "silver"}),
    ("C-403", "autohub", "sedan", "Honda", "Civic", "Honda Civic 1.8 i-VTEC 2019", 2019, "Karachi", "AutoHub, Shahrah-e-Faisal", 52 * L,
     {"mileage_km": 71000, "transmission": "automatic", "fuel": "petrol", "color": "black"}),
    ("C-404", "autohub", "sedan", "Honda", "City", "Honda City 1.2 2021", 2021, "Karachi", "AutoHub, Shahrah-e-Faisal", 38 * L,
     {"mileage_km": 45000, "transmission": "manual", "fuel": "petrol", "color": "white"}),
    ("C-405", "autohub", "hatchback", "Suzuki", "Cultus", "Suzuki Cultus VXL 2022", 2022, "Karachi", "AutoHub, Shahrah-e-Faisal", 33 * L,
     {"mileage_km": 30000, "transmission": "manual", "fuel": "petrol", "color": "red"}),
    ("C-406", "autohub", "hatchback", "Suzuki", "Wagon R", "Suzuki Wagon R VXL 2022", 2022, "Karachi", "AutoHub, Shahrah-e-Faisal", 28 * L,
     {"mileage_km": 33000, "transmission": "manual", "fuel": "petrol", "color": "white"}),
    ("C-407", "autohub", "suv", "Hyundai", "Tucson", "Hyundai Tucson FWD A/T GLS 2022", 2022, "Karachi", "AutoHub, Shahrah-e-Faisal", 79 * L,
     {"mileage_km": 27000, "transmission": "automatic", "fuel": "petrol", "color": "grey"}),
    ("C-408", "autohub", "suv", "MG", "HS", "MG HS Essence 2023", 2023, "Karachi", "AutoHub, Shahrah-e-Faisal", 74 * L,
     {"mileage_km": 14000, "transmission": "automatic", "fuel": "petrol", "color": "blue"}),
    ("C-409", "autohub", "sedan", "Hyundai", "Elantra", "Hyundai Elantra 2.0 GLS 2022", 2022, "Karachi", "AutoHub, Shahrah-e-Faisal", 66 * L,
     {"mileage_km": 22000, "transmission": "automatic", "fuel": "petrol", "color": "white"}),
    ("C-410", "autohub", "pickup", "Toyota", "Hilux", "Toyota Hilux Revo V 2021", 2021, "Karachi", "AutoHub, Shahrah-e-Faisal", int(1.15 * CR),
     {"mileage_km": 48000, "transmission": "automatic", "fuel": "diesel", "color": "white"}),
]


def _describe_property(subtype, specs, area, city):
    bits = [specs.get("size", "")]
    if specs.get("beds"):
        bits.append(f"{specs['beds']} bed / {specs.get('baths', '?')} bath")
    if specs.get("possession"):
        bits.append("possession available" if specs["possession"] == "yes" else "file / no possession yet")
    return f"{subtype.title()} in {area}, {city}. " + ", ".join(b for b in bits if b) + "."


def seed_if_empty() -> None:
    with engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(agencies)).scalar():
            return
        for aid, name, kind, city, phone, username, pwd in AGENCIES:
            pwd = os.getenv(f"ADMIN_PASSWORD_{aid.upper()}", pwd)
            conn.execute(insert(agencies).values(id=aid, name=name, kind=kind, city=city, phone=phone,
                                                 username=username, password_hash=hash_password(pwd)))
        for pid, ag, sub, title, city, area, price, specs in PROPERTIES:
            conn.execute(insert(listings).values(
                id=pid, agency_id=ag, category="property", title=title, subtype=sub, city=city, area=area,
                price_pkr=price, specs=specs, description=_describe_property(sub, specs, area, city),
                status="active", created_at=now()))
        for cid, ag, sub, make, model, title, year, city, area, price, specs in CARS:
            desc = (f"{year} {make} {model}, {specs['mileage_km']:,} km, {specs['transmission']}, "
                    f"{specs['fuel']}, {specs['color']}. Inspected, original documents.")
            conn.execute(insert(listings).values(
                id=cid, agency_id=ag, category="car", title=title, subtype=sub, make=make, model=model, year=year,
                city=city, area=area, price_pkr=price, specs=specs, description=desc, status="active",
                created_at=now()))
