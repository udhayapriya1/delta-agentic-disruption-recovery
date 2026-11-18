trigger DeltaDisruptionEvent on Delta_Disruption_Event__e (after insert) {
    DeltaDisruptionEventHandler.handle(Trigger.new);
}
