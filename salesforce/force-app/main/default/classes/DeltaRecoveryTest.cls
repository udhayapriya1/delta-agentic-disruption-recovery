@IsTest private class DeltaRecoveryTest {
    private class Fixture implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest request) {
            System.assert(request.getEndpoint().startsWith('callout:Delta_Integration/'));
            HttpResponse response=new HttpResponse();response.setStatusCode(200);response.setBody('{"source":"APEX_TEST_FIXTURE"}');response.setHeader('X-Trace-ID','test-trace');return response;
        }
    }
    private class Failed implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest request) { throw new CalloutException('fixture timeout'); }
    }
    @TestSetup static void setupPermissions() {
        Id permissionId=[SELECT Id FROM PermissionSet WHERE Name='Delta_Recovery_Operator' LIMIT 1].Id;
        if ([SELECT COUNT() FROM PermissionSetAssignment WHERE AssigneeId=:UserInfo.getUserId() AND PermissionSetId=:permissionId]==0) insert new PermissionSetAssignment(AssigneeId=UserInfo.getUserId(),PermissionSetId=permissionId);
    }
    @IsTest static void allowedRoutesAndFailures() {
        System.runAs(new User(Id=UserInfo.getUserId())) {
        Test.setMock(HttpCalloutMock.class,new Fixture());
        List<DeltaRecoveryAction.Input> requests=new List<DeltaRecoveryAction.Input>();
        for (String action:new List<String>{'status','options','context','rebook','voucher','acceptance','escalate','unsupported'}) {
            DeltaRecoveryAction.Input i=new DeltaRecoveryAction.Input();i.action=action;i.pnr='D00001';i.requestJson='{}';requests.add(i);
        }
        Test.startTest();List<DeltaRecoveryAction.Output> results=DeltaRecoveryAction.execute(requests);Test.stopTest();
        System.assertEquals(200,results[0].statusCode);System.assertEquals('test-trace',results[0].traceId);System.assertEquals(400,results[7].statusCode);

        }
    }
    @IsTest static void missingBookingRejected() {
        System.runAs(new User(Id=UserInfo.getUserId())) {
        DeltaRecoveryAction.Input i=new DeltaRecoveryAction.Input();i.action='status';i.pnr='malicious';
        System.assertEquals(400,DeltaRecoveryAction.execute(new List<DeltaRecoveryAction.Input>{i})[0].statusCode);

        }
    }
    @IsTest static void timeoutHasNoInventedConfirmation() {
        System.runAs(new User(Id=UserInfo.getUserId())) {
        Test.setMock(HttpCalloutMock.class,new Failed());DeltaRecoveryAction.Input i=new DeltaRecoveryAction.Input();i.action='status';i.pnr='D00001';
        Test.startTest();System.assertEquals(503,DeltaRecoveryAction.execute(new List<DeltaRecoveryAction.Input>{i})[0].statusCode);Test.stopTest();

        }
    }
    @IsTest static void caseUpsertIsIdempotent() {
        System.runAs(new User(Id=UserInfo.getUserId())) {
        DeltaCaseAction.Input i=new DeltaCaseAction.Input();i.transactionId='SYN-ABCDEF123456';i.summary='Synthetic confirmed transaction';
        Id first=DeltaCaseAction.execute(new List<DeltaCaseAction.Input>{i})[0].caseId;
        Id second=DeltaCaseAction.execute(new List<DeltaCaseAction.Input>{i})[0].caseId;
        System.assertEquals(first,second);
        i.transactionId='unverified';Boolean denied=false;
        try { DeltaCaseAction.execute(new List<DeltaCaseAction.Input>{i}); } catch (IllegalArgumentException e) { denied=true; }
        System.assert(denied);

        }
    }
    @IsTest static void confirmationFlowUsesGuardedUpsert() {
        System.runAs(new User(Id=UserInfo.getUserId())) {
            Map<String,Object> inputs=new Map<String,Object>{'transactionId'=>'SYN-FLOWTEST1234','summary'=>'Actual Flow test with synthetic confirmation'};
            Flow.Interview.createInterview('Delta_Record_Confirmed_Recovery',inputs).start();
            System.assertEquals(1,[SELECT COUNT() FROM Case WHERE Delta_Transaction_Id__c='SYN-FLOWTEST1234']);
        }
    }
    @IsTest static void unauthorizedUserCannotInvoke() {
        User u=new User(Alias='dltnop',Email='unit@example.invalid',EmailEncodingKey='UTF-8',LastName='SyntheticDenied',LanguageLocaleKey='en_US',LocaleSidKey='en_US',TimeZoneSidKey='America/New_York',ProfileId=[SELECT Id FROM Profile WHERE Name='Standard User' LIMIT 1].Id,Username='delta.denied.'+String.valueOf(DateTime.now().getTime())+'@example.invalid');
        insert u;
        System.runAs(u) {
            Boolean denied=false;
            try { DeltaRecoveryAction.execute(new List<DeltaRecoveryAction.Input>()); } catch (SecurityException e) { denied=true; }
            System.assert(denied,'Missing custom permission must deny the action');
        }
    }
}
