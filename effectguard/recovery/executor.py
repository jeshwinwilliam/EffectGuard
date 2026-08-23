from __future__ import annotations

from ..models import ObservedStatus, RecoveryActionType, RecoveryStatus


def execute_recovery_plan(env, plan) -> RecoveryStatus:
    env.runtime_log.append(
        event_type="recovery_plan_created",
        sim_time_ms=env.clock.peek(),
        run_id=env.runtime.run_id,
        seed=env.config.seed,
        workflow_id=env.workflow.workflow_id,
        workflow_instance_id=env.config.workflow_instance_id,
        strategy=env.config.strategy,
        operation_id="reserve_a",
        operation_type="recovery",
        effect_class="PURE",
        attempt=0,
        observed_status="SUCCESS",
        compensation_indicator=False,
        selected_invalidated_operations=list(plan.selected_invalidated_operations),
    )
    env.selected_invalidated_operations = plan.selected_invalidated_operations
    env.preserved_operations = plan.preserved_operations

    for action in plan.compensation_actions:
        env.runtime_log.append(
            event_type="compensation_started",
            sim_time_ms=env.clock.peek(),
            run_id=env.runtime.run_id,
            seed=env.config.seed,
            workflow_id=env.workflow.workflow_id,
            workflow_instance_id=env.config.workflow_instance_id,
            strategy=env.config.strategy,
            operation_id=action.operation_id,
            operation_type="recovery",
            effect_class="COMPENSABLE",
            attempt=0,
            observed_status="PENDING",
            compensation_indicator=True,
        )
        if action.operation_id == "create_shipment":
            existing = next(
                (shipment for shipment in env.shipments.actual_records() if shipment.supplier_id == action.target_supplier_id and shipment.status == "ACTIVE"),
                None,
            )
            if existing is None:
                continue
            result = env.shipments.cancel(idempotency_key=action.idempotency_key or "", target_logical_call_id=existing.logical_call_id)
        elif action.operation_id == "reserve_b":
            existing = next(
                (record for record in env.reservations.actual_records() if record.supplier_id == action.target_supplier_id and record.status == "ACTIVE"),
                None,
            )
            if existing is None:
                continue
            env.reservations.release(reservation_id=existing.reservation_id)
            result = type("Result", (), {"observed_status": ObservedStatus.SUCCESS})()
        else:
            result = type("Result", (), {"observed_status": ObservedStatus.FAILURE})()
        if result.observed_status is not ObservedStatus.SUCCESS:
            env.compensation_failures += 1
            env.recovery_status = RecoveryStatus.RECOVERY_FAILED
            env.runtime_log.append(
                event_type="recovery_failed",
                sim_time_ms=env.clock.peek(),
                run_id=env.runtime.run_id,
                seed=env.config.seed,
                workflow_id=env.workflow.workflow_id,
                workflow_instance_id=env.config.workflow_instance_id,
                strategy=env.config.strategy,
                operation_id=action.operation_id,
                operation_type="recovery",
                effect_class="COMPENSABLE",
                attempt=0,
                observed_status="FAILURE",
                compensation_indicator=True,
            )
            return RecoveryStatus.RECOVERY_FAILED
        env.compensation_count += 1
        env.runtime_log.append(
            event_type="compensation_completed",
            sim_time_ms=env.clock.peek(),
            run_id=env.runtime.run_id,
            seed=env.config.seed,
            workflow_id=env.workflow.workflow_id,
            workflow_instance_id=env.config.workflow_instance_id,
            strategy=env.config.strategy,
            operation_id=action.operation_id,
            operation_type="recovery",
            effect_class="COMPENSABLE",
            attempt=0,
            observed_status="SUCCESS",
            compensation_indicator=True,
        )

    for action in plan.recomputation_actions:
        if action.operation_id == "create_shipment":
            env.runtime_log.append(
                event_type="recomputation_started",
                sim_time_ms=env.clock.peek(),
                run_id=env.runtime.run_id,
                seed=env.config.seed,
                workflow_id=env.workflow.workflow_id,
                workflow_instance_id=env.config.workflow_instance_id,
                strategy=env.config.strategy,
                operation_id="create_shipment",
                operation_type="recovery",
                effect_class="COMPENSABLE",
                attempt=0,
                observed_status="PENDING",
                compensation_indicator=False,
            )
            env.op_create_shipment(supplier_id=action.target_supplier_id or "A", recovery=True)
        elif action.operation_id == "build_procurement_plan":
            env.runtime_log.append(
                event_type="recomputation_started",
                sim_time_ms=env.clock.peek(),
                run_id=env.runtime.run_id,
                seed=env.config.seed,
                workflow_id=env.workflow.workflow_id,
                workflow_instance_id=env.config.workflow_instance_id,
                strategy=env.config.strategy,
                operation_id="build_procurement_plan",
                operation_type="recovery",
                effect_class="PURE",
                attempt=0,
                observed_status="PENDING",
                compensation_indicator=False,
            )
            env.op_build_plan(supplier_id=action.target_supplier_id or "A", recovery=True)
    env.recovery_status = RecoveryStatus.RECOVERED
    env.runtime_log.append(
        event_type="recovery_completed",
        sim_time_ms=env.clock.peek(),
        run_id=env.runtime.run_id,
        seed=env.config.seed,
        workflow_id=env.workflow.workflow_id,
        workflow_instance_id=env.config.workflow_instance_id,
        strategy=env.config.strategy,
        operation_id="reserve_a",
        operation_type="recovery",
        effect_class="PURE",
        attempt=0,
        observed_status="SUCCESS",
        compensation_indicator=False,
    )
    return RecoveryStatus.RECOVERED
