#!/bin/sh
# Same authorized delta-dev org. Review paths and Named Credential endpoint first.
set -eu
cd "$(dirname "$0")/.."
sf project deploy start --target-org delta-dev \
 --source-dir salesforce/force-app/main/default/objects \
 --source-dir salesforce/force-app/main/default/classes \
 --source-dir salesforce/force-app/main/default/triggers \
 --source-dir salesforce/force-app/main/default/flows \
 --source-dir salesforce/force-app/main/default/customPermissions \
 --source-dir salesforce/force-app/main/default/customMetadata \
 --source-dir salesforce/force-app/main/default/permissionsets \
 --source-dir salesforce/force-app/main/default/externalCredentials \
 --source-dir salesforce/force-app/main/default/namedCredentials \
 --test-level RunSpecifiedTests --tests DeltaRecoveryTest DeltaDisruptionEventTest --wait 10
sf project deploy start --target-org delta-dev \
 --source-dir salesforce/force-app/main/default/genAiFunctions \
 --source-dir salesforce/force-app/main/default/genAiPlugins --wait 10
sf agent deactivate --api-name Delta_Medallion_Recovery --target-org delta-dev
sf project deploy start --target-org delta-dev \
 --source-dir salesforce/force-app/main/default/aiAgentDefinitionVersions --wait 10
sf agent activate --api-name Delta_Medallion_Recovery --target-org delta-dev
