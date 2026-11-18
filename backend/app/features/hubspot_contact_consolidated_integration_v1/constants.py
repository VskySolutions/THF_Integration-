"""Maconomy customer discovery settings for the v1 integration."""

SYNC_WINDOW_DAYS = 1
CUSTOMER_SYNCED_VERSION_FIELD = "customerremark26"
CUSTOMER_NUMBER_FIELD = "customernumber"
VERSION_FIELD = "versionnumber"

CUSTOMER_CARD_FIELDS = [
    "changeddate",
    "createddate",
    "country",
    "customerremark26",
    "customernumber",
    "departmentnumber",
    "electronicmailaddress",
    "entityname",
    "locationname",
    "name1",
    "name2",
    "name3",
    "postaldistrict",
    "specification1name",
    "specification5name",
    "specification6name",
    "telephone",
    "theaccountmanagername",
    "versionnumber",
    "zipcode",
]

SPECIFICATION1_FIELDS = ["specification1name", "description"]
