SYNC_WINDOW_DAYS = 2

CUSTOMER_SYNCED_VERSION_FIELD = "customerremark26"
CONTACT_SYNCED_VERSION_FIELD = "remark5"
CONTACT_MASTER_FIELD = "remark4"

CUSTOMER_FILTER_BATCH_SIZE = 50
EMAIL_BACK_QUERY_BATCH_SIZE = 5
MID_RUN_BACK_QUERY_CONCURRENCY = 10

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
    "lastname",
    "mobilephone",
    "name1",
    "name2",
    "position",
    "remark1",
    "remark4",
    "remark5",
    "telephone",
    "telephone2",
    "personaltitle",
    "versionnumber",
]

CUSTOMER_CONTACT_LOOKUP_FIELDS = [
    "customernumber",
    "name1",
    "theaccountmanagername",
    "specification1name",
]
SPECIFICATION1_FIELDS = ["specification1name", "description"]

CUSTOMER_NUMBER_FIELD = "customernumber"
CONTACT_PERSON_NUMBER_FIELD = "contactpersonnumber"
CONTACT_COMPANY_NUMBER_FIELD = "contactcompanynumber"
EMAIL_FIELD = "electronicmailaddress"
VERSION_FIELD = "versionnumber"

PARENT_COMPANY_NAME_FIELD = "parent_customer_name1"
PARENT_CUSTOMER_CSE_FIELD = "parent_customer_cse"
PARENT_CUSTOMER_INDUSTRY_FIELD = "parent_customer_industry"
