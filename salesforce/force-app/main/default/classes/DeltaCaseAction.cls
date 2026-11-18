public with sharing class DeltaCaseAction {
    public class Input {
        @InvocableVariable(required=true) public String transactionId;
        @InvocableVariable(required=true) public String summary;
    }
    public class Output { @InvocableVariable public Id caseId; }
    @InvocableMethod(label='Delta Record Confirmed Recovery' description='Upserts a synthetic service Case using the external transaction ID; call only after authoritative API confirmation.')
    public static List<Output> execute(List<Input> inputs) {
        if (!FeatureManagement.checkPermission('Delta_Recovery_Action')) throw new SecurityException('Recovery action permission required');
        List<Case> cases=new List<Case>();
        for (Input item:inputs) {
            if (String.isBlank(item.transactionId) || !Pattern.matches('SYN-[A-Z0-9]{12}',item.transactionId)) throw new IllegalArgumentException('Verified synthetic transaction ID required');
            cases.add(new Case(Delta_Transaction_Id__c=item.transactionId,Subject='Synthetic disruption recovery '+item.transactionId,Status='New',Origin='Web',Description=item.summary));
        }
        Database.UpsertResult[] results=Database.upsert(cases,Case.Fields.Delta_Transaction_Id__c,AccessLevel.USER_MODE);
        List<Output> outputs=new List<Output>();
        for (Database.UpsertResult result:results) { Output o=new Output();o.caseId=result.getId();outputs.add(o); }
        return outputs;
    }
}
