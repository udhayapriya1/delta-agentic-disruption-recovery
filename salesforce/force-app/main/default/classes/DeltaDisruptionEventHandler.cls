/** Native proactive intake. No passenger message, booking, or voucher is sent. */
public without sharing class DeltaDisruptionEventHandler {
    public static void handle(List<Delta_Disruption_Event__e> events) {
        Map<String, Case> pending = new Map<String, Case>();
        for (Delta_Disruption_Event__e event : events) {
            if (event.Passenger_Ref__c != 'P001' || event.Flight_Ref__c != 'DL-SYN0' || event.Event_Type__c != 'CANCELLED' ||
                String.isBlank(event.Event_Key__c) || !Pattern.matches('DEMO-[A-Z0-9-]{1,60}', event.Event_Key__c)) continue;
            String key = 'EVT-' + event.Event_Key__c;
            pending.put(key, new Case(Delta_Transaction_Id__c=key,
                Subject='Synthetic proactive cancellation ' + event.Event_Key__c,
                Status='New', Origin='Web', Description=JSON.serialize(new Map<String,Object>{
                    'synthetic'=>true, 'passenger_ref'=>'P001', 'flight_ref'=>'DL-SYN0',
                    'event_key'=>event.Event_Key__c, 'status'=>'CANCELLED',
                    'passenger_notification_sent'=>false, 'human_acknowledged'=>false,
                    'next_step'=>'Authenticated passenger must select and authorize any rebooking'})));
        }
        if (pending.isEmpty()) return;
        // Redelivery is insert-only: never reset a Case already being handled.
        for (Case existing : [SELECT Delta_Transaction_Id__c FROM Case WHERE Delta_Transaction_Id__c IN :pending.keySet()]) {
            pending.remove(existing.Delta_Transaction_Id__c);
        }
        if (!pending.isEmpty()) {
            Database.SaveResult[] results=Database.insert(pending.values(), false);
            for (Database.SaveResult result:results) {
                if (!result.isSuccess()) {
                    // Concurrent duplicate publication is safely rejected by unique external ID.
                    // Other errors are surfaced for subscriber retry; never silently discard them.
                    for (Database.Error error:result.getErrors()) {
                        if (error.getStatusCode()!=StatusCode.DUPLICATE_VALUE) throw new EventBus.RetryableException('Synthetic proactive Case persistence unavailable');
                    }
                }
            }
        }
    }
}
