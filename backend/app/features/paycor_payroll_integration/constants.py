"""Constants and static configurations for Paycor Payroll Integration."""

import enum

PAYCOR_PAYROLL_ROUTER_PREFIX = "/paycor/payroll"
PAYCOR_PAYROLL_TAG = "paycor-payroll-integration"


class IntegrationStatus(str, enum.Enum):
    """Execution status for payroll integration attempts."""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"


class IntegrationAction(str, enum.Enum):
    """Operation action performed during payroll sync."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"


# Default configuration constants
DEFAULT_COMPANY_NUMBER = "100"
DEFAULT_TRANSACTION_TYPE = "Payroll"
DEFAULT_GL_ACCOUNT_NUMBER = "5787"
DEFAULT_TYPE_OF_ENTRY = "g"
DEFAULT_LEGAL_ENTITY_ID = 158797

# Mapping: Department description keywords -> Maconomy internal entity codes
DEPARTMENT_ENTITY_CODE_MAP = {
    "ASSURANCE": "1",
    "TAX": "2",
    "ADMIN": "3",
    "GCS": "4",
    "CAS": "5",
    "DEFAULT": "-",
}

# Mapping: Work location names -> Maconomy shortform codes (specification4name)
LOCATION_NAME_TO_SHORTFORM: dict[str, str] = {
    "Dade City": "DDC",
    "Lakeland": "LKL",
    "Panama City": "PCB",
    "Tallahassee": "TLH",
    "Tampa": "TPA",
    "Bainbridge": "-",
    "Default": "-",
}

# Static lookup: Paycor Department UUID -> Maconomy Location Shortform
STATIC_DEPARTMENT_WORK_LOCATIONS: dict[str, str] = {
    "025211eb-e826-0000-0000-00004d6c0200": "TPA",
    "122fc6bb-e25d-0000-0000-00004d6c0200": "PCB",
    "14036cc3-f59d-0000-0000-00004d6c0200": "TLH",
    "14435236-344d-0000-0000-00004d6c0200": "TLH",
    "19f0fd04-968a-0000-0000-00004d6c0200": "PCB",
    "1a109689-0d4c-0000-0000-00004d6c0200": "TLH",
    "20b3c46e-037b-0000-0000-00004d6c0200": "-",    # Bainbridge
    "231fdc2a-2185-0000-0000-00004d6c0200": "TLH",
    "24f2af57-3f60-0000-0000-00004d6c0200": "TLH",
    "25831c2a-1ae3-0000-0000-00004d6c0200": "TLH",
    "25e4ca60-e2c1-0000-0000-00004d6c0200": "TPA",
    "2a76a5de-aca3-0000-0000-00004d6c0200": "PCB",
    "2c87de22-a0b5-0000-0000-00004d6c0200": "PCB",
    "2d9516ee-80de-0000-0000-00004d6c0200": "PCB",
    "3487c1a2-d107-0000-0000-00004d6c0200": "TPA",
    "43554982-36fd-0000-0000-00004d6c0200": "TLH",
    "44a69338-d578-0000-0000-00004d6c0200": "TLH",
    "46450bc6-adeb-0000-0000-00004d6c0200": "TLH",
    "49381a20-199a-0000-0000-00004d6c0200": "TLH",
    "4d0b2f58-f5d0-0000-0000-00004d6c0200": "TLH",
    "4d14d4cd-bf66-0000-0000-00004d6c0200": "TLH",
    "4e59f031-9797-0000-0000-00004d6c0200": "TLH",
    "5194afa0-1747-0000-0000-00004d6c0200": "TLH",
    "5556f911-3938-0000-0000-00004d6c0200": "TLH",
    "5bd71c31-4898-0000-0000-00004d6c0200": "TPA",
    "5cfcfa32-c9c3-0000-0000-00004d6c0200": "-",    # Bainbridge
    "5fd7354a-5837-0000-0000-00004d6c0200": "TPA",
    "689da855-421b-0000-0000-00004d6c0200": "TLH",
    "68cdcf54-865b-0000-0000-00004d6c0200": "LKL",
    "6c306584-bd96-0000-0000-00004d6c0200": "TLH",
    "72c630f4-889b-0000-0000-00004d6c0200": "TLH",
    "77fb2085-da94-0000-0000-00004d6c0200": "TPA",
    "83e2ead1-e178-0000-0000-00004d6c0200": "PCB",
    "83ede267-689a-0000-0000-00004d6c0200": "TPA",
    "98ae2f9a-a544-0000-0000-00004d6c0200": "TLH",
    "a52a0df1-f37c-0000-0000-00004d6c0200": "TPA",
    "a531f8d8-2f49-0000-0000-00004d6c0200": "TLH",
    "a6679f89-c216-0000-0000-00004d6c0200": "TPA",
    "ad1a8fd4-49b8-0000-0000-00004d6c0200": "-",    # Bainbridge
    "ae656cbe-b33f-0000-0000-00004d6c0200": "TLH",
    "afede43a-7df7-0000-0000-00004d6c0200": "TPA",
    "b227edd3-48bc-0000-0000-00004d6c0200": "-",    # Bainbridge
    "b51fb4f0-e98f-0000-0000-00004d6c0200": "TPA",
    "b7844583-d32a-0000-0000-00004d6c0200": "TPA",
    "b7fd451b-165b-0000-0000-00004d6c0200": "PCB",
    "b8baa3f0-da33-0000-0000-00004d6c0200": "TLH",
    "bc1bf7c0-fe22-0000-0000-00004d6c0200": "TLH",
    "bc7aba28-c1ef-0000-0000-00004d6c0200": "-",    # Bainbridge
    "c3e974a1-ad93-0000-0000-00004d6c0200": "TPA",
    "c5585c58-76a2-0000-0000-00004d6c0200": "TPA",
    "c6f5854d-ef1c-0000-0000-00004d6c0200": "TLH",
    "cb3582a2-4258-0000-0000-00004d6c0200": "TLH",
    "cf8615ed-1ea2-0000-0000-00004d6c0200": "TPA",
    "d192b253-87e0-0000-0000-00004d6c0200": "TLH",
    "d6815922-ef66-0000-0000-00004d6c0200": "LKL",
    "d7dcfc85-ed82-0000-0000-00004d6c0200": "TLH",
    "da5b1528-5ecb-0000-0000-00004d6c0200": "-",    # Bainbridge
    "de5ef353-a7ca-0000-0000-00004d6c0200": "TLH",
    "e3d2c31a-5e2d-0000-0000-00004d6c0200": "TLH",
    "e4592b33-500a-0000-0000-00004d6c0200": "TPA",
    "e4644182-5a76-0000-0000-00004d6c0200": "TLH",
    "e64c6bdc-4cce-0000-0000-00004d6c0200": "TLH",
    "eaefe756-d922-0000-0000-00004d6c0200": "TLH",
    "f35381ac-290b-0000-0000-00004d6c0200": "TLH",
    "f3fc3032-ba72-0000-0000-00004d6c0200": "PCB",
    "f707722a-b084-0000-0000-00004d6c0200": "TLH",
    "f8c600e7-f2e5-0000-0000-00004d6c0200": "DDC",
    "f9c02f81-2386-0000-0000-00004d6c0200": "TLH",
    "fdcf4af1-fd81-0000-0000-00004d6c0200": "TLH",
    "fe0fb984-7464-0000-0000-00004d6c0200": "TPA",
    "fe7fa2c6-22b4-0000-0000-00004d6c0200": "-",    # Bainbridge
    "009b453b-0d7f-0000-0000-00004d6c0200": "TPA",
    "039158b4-ddaa-0000-0000-00004d6c0200": "PCB",
    "03de8cd0-ff60-0000-0000-00004d6c0200": "TPA",
    "0c1fb549-6366-0000-0000-00004d6c0200": "LKL",
    "108875e6-2832-0000-0000-00004d6c0200": "LKL",
    "10a305f4-64bf-0000-0000-00004d6c0200": "TLH",
    "115a26c6-6233-0000-0000-00004d6c0200": "TLH",
    "12355494-01a9-0000-0000-00004d6c0200": "TPA",
    "124aac51-0bab-0000-0000-00004d6c0200": "DDC",
    "14ce6756-f7a3-0000-0000-00004d6c0200": "LKL",
    "18a97481-fdfd-0000-0000-00004d6c0200": "LKL",
    "1b984ec3-025c-0000-0000-00004d6c0200": "LKL",
    "1f869307-8dfd-0000-0000-00004d6c0200": "TLH",
    "249df886-6543-0000-0000-00004d6c0200": "TLH",
    "24e07f77-5b98-0000-0000-00004d6c0200": "TLH",
    "270c4b32-ccbe-0000-0000-00004d6c0200": "PCB",
    "29aa6345-3b95-0000-0000-00004d6c0200": "DDC",
    "2a450bff-de17-0000-0000-00004d6c0200": "TLH",
    "2d8f3e83-9179-0000-0000-00004d6c0200": "-",    # Bainbridge
    "2ee65c28-105c-0000-0000-00004d6c0200": "LKL",
    "310d5e8a-a053-0000-0000-00004d6c0200": "-",    # Bainbridge
    "3600db30-bb8b-0000-0000-00004d6c0200": "TPA",
    "37547836-8fa6-0000-0000-00004d6c0200": "TPA",
    "396aa466-dc1a-0000-0000-00004d6c0200": "TPA",
    "3b010e2d-c116-0000-0000-00004d6c0200": "TPA",
    "3c399d2b-1d60-0000-0000-00004d6c0200": "TLH",
    "3daadcfc-5d38-0000-0000-00004d6c0200": "LKL",
    "3e60df7d-2140-0000-0000-00004d6c0200": "-",    # Bainbridge
    "4220f11f-f75b-0000-0000-00004d6c0200": "TPA",
}

