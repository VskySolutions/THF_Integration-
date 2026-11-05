# Caseware Cloud Field Mapping

| SourceField | TargetField | PurposeOfField |
|---|---|---|
| `jobs.jobnumber` | `Entity.EntityNo` | Provides a unique reference for the engagement. It helps find the correct Entity during future updates and prevents duplicate records. Test records receive a `VSKY-` prefix. |
| `jobs.jobname` | `Entity.Name` | Displays the engagement name as the main client or organization name. Changes to the name are transferred during the next synchronization. |
| `jobs.jobname` | `Entity.OperatingName` | Stores the engagement name as the operating name and keeps the displayed names consistent between the two systems. |
| `countries.isocode` | `Entity.CountryCode` | Provides the standard two-letter country code, such as `US`, `CA`, or `GB`, based on the country selected in the engagement. |
| `Hardcode "Client"` | `Entity.OwnerType` | Identifies the Entity as a client record and places it under the correct category. |
| `Hardcode "A"` | `Entity.Type` | Sets the standard Entity type required for records created and maintained by the integration. |
| `Hardcode "Corporation"` | `Entity.OrganizationType` | Classifies a newly created Entity as an organization or corporation. This value is set when the Entity is first created. |
| `jobs.name1` | `EntityAddress.Name` | Stores the customer or location name connected to the business address. It helps identify whose address is displayed. |
| `jobs.name2` | `EntityAddress.Address1` | Stores the first and main address line, normally containing the building number, street name, or main location details. |
| `jobs.name3` | `EntityAddress.Address2` | Stores additional address information, such as a building, floor, unit, or area name. |
| `jobs.name4` | `EntityAddress.Address3` | Stores any remaining address information when the complete address requires a third line. |
| `jobs.postaldistrict` | `EntityAddress.City` | Records the city, town, or locality of the customer's business address. |
| `jobs.zipcode` | `EntityAddress.PostalCode` | Records the postal code or ZIP code and helps complete the customer's location information. |
| `jobs.telephone` | `EntityAddress.PhoneNumber` | Stores the telephone number connected to the customer's business address. |
| `jobs.country` | `EntityAddress.Country` | Records the country belonging to the business address. For US and Canadian records, the two-letter country code is used. |
| `jobs.country` | `EntityAddress.Province` | Currently fills the Province field for US and Canadian addresses. This should be confirmed because a state or province value would normally be expected. |
| `Hardcode "Business"` | `EntityAddress.AddressCategory` | Marks the address as a business address. One business address is maintained for each synchronized Entity. |
