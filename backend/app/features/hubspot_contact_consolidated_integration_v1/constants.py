"""Maconomy customer discovery settings for the v1 integration."""

SYNC_WINDOW_DAYS = 1
CUSTOMER_SYNCED_VERSION_FIELD = "customerremark26"
CUSTOMER_NUMBER_FIELD = "customernumber"
CONTACT_SYNCED_VERSION_FIELD = "remark5"
CONTACT_MASTER_FIELD = "remark4"
CONTACT_PERSON_NUMBER_FIELD = "contactpersonnumber"
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

CONTACT_PERSON_FIELDS = [
    "changeddate",
    "contactcompanynumber",
    "contactpersonnumber",
    "createddate",
    "country",
    "electronicmailaddress",
    "firstname",
    "middlename",
    "lastname",
    "mobilephone",
    "name1",
    "name2",
    "name3",
    "position",
    "remark1",
    "remark4",
    "remark5",
    "telephone",
    "telephone2",
    "personaltitle",
    "versionnumber",
    "postaldistrict",
    "zipcode"
]

SPECIFICATION1_FIELDS = ["specification1name", "description"]
SPECIFICATION6_FIELDS = ["specification6name", "description"]

JOB_CSE_MARKET_FIELDS = [
    "jobnumber",
    "customernumber",
    "specification4name",
    "accountmanagername",
    "changeddate",
    "createddate",
]
