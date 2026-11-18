public with sharing class DeltaRecoveryAction {
    public class Input {
        @InvocableVariable(required=true) public String action;
        @InvocableVariable public String pnr;
        @InvocableVariable public String requestJson;
    }
    public class Output {
        @InvocableVariable public Integer statusCode;
        @InvocableVariable public String responseJson;
        @InvocableVariable public String traceId;
    }
    @InvocableMethod(label='Delta Guarded Recovery API' description='Calls a fixed recovery endpoint through Delta_Integration Named Credential; API enforces passenger binding and policies.' callout=true)
    public static List<Output> execute(List<Input> inputs) {
        if (!FeatureManagement.checkPermission('Delta_Recovery_Action')) {
            throw new SecurityException('Recovery action permission required');
        }
        Map<String,String> routes = new Map<String,String>{'status'=>'/flight-status','options'=>'/rebook-options','acceptance'=>'/acceptance','rebook'=>'/rebook','voucher'=>'/voucher','escalate'=>'/escalate','context'=>'/customer-context'};
        List<Output> outputs = new List<Output>();
        for (Input item : inputs) {
            Output result = new Output();
            if (!routes.containsKey(item.action)) {
                result.statusCode=400; result.responseJson='{"error":"Unsupported action"}'; outputs.add(result); continue;
            }
            Boolean readOnly = item.action=='status' || item.action=='options' || item.action=='context';
            String route=routes.get(item.action);
            if (item.action=='status' || item.action=='options') {
                if (item.pnr==null || !Pattern.matches('D[0-9]{5}',item.pnr)) {
                    result.statusCode=400; result.responseJson='{"error":"Invalid synthetic booking reference"}'; outputs.add(result); continue;
                }
                route+='?pnr='+EncodingUtil.urlEncode(item.pnr,'UTF-8');
            }
            HttpRequest request = new HttpRequest();
            request.setEndpoint('callout:Delta_Integration'+route);
            request.setMethod(readOnly?'GET':'POST'); request.setTimeout(20000);
            request.setHeader('Content-Type','application/json');
            if (!readOnly) request.setBody(String.isBlank(item.requestJson)?'{}':item.requestJson);
            try {
                HttpResponse response=new Http().send(request);
                result.statusCode=response.getStatusCode();
                result.responseJson=response.getBody();
                if (item.action=='context' && result.statusCode==200) {
                    Map<String,Object> context=(Map<String,Object>)JSON.deserializeUntyped(result.responseJson);
                    Map<String,Object> graph=(Map<String,Object>)context.get('data360_context');
                    if (graph==null || graph.get('profile_binding_verified')!=true) {
                        result.statusCode=503;
                        result.responseJson='{"error":"Verified Data 360 REST profile required; eligibility blocked"}';
                    }
                }
                result.traceId=response.getHeader('X-Trace-ID');
                if (result.traceId==null) result.traceId=response.getHeader('x-trace-id');
            } catch (CalloutException ex) {
                String category=ex.getMessage().contains('uncommitted')?'UNCOMMITTED_TRANSACTION':ex.getMessage().contains('credential')?'CREDENTIAL_ACCESS':'CALLOUT_UNAVAILABLE';
                result.statusCode=503; result.responseJson=JSON.serialize(new Map<String,Object>{'error'=>'External dependency unavailable; do not infer a booking','error_category'=>category});
            }
            outputs.add(result);
        }
        return outputs;
    }
}
