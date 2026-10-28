import type { GenerateRequest, GenerateResponse, SaveOperationResponse } from '../services/api';
import { ApiError } from '../services/api';
import { buildGenerateRequest, savedPlanVraDiffers, type WorkState } from './workMachine';

export interface SavePlanDeps {
  generate(body: GenerateRequest): Promise<GenerateResponse>;
  saveOperation(body: { kind: 'plan'; plan_id: string }): Promise<SaveOperationResponse>;
}

/**
 * Persist the reviewed plan by id. The backend stores the plan as generated; a VRA prescription
 * computed (or removed) afterwards is not attached to it, so in that case the plan is regenerated
 * once with the current VRA (persist:false) and the new id is saved. The caller shows `regenerated`.
 */
export async function savePlan(
  s: WorkState, deps: SavePlanDeps,
): Promise<{ operationId: string; regenerated?: GenerateResponse }> {
  if (s.result === null) throw new Error('no plan to save');
  let regenerated: GenerateResponse | undefined;
  let planId = s.result.planId;
  if (planId === null || savedPlanVraDiffers(s)) {
    regenerated = await deps.generate(buildGenerateRequest({ ...s, phase: 'generated' }, false));
    planId = regenerated.plan_id;
  }
  const saved = await deps.saveOperation({ kind: 'plan', plan_id: planId });
  if (!saved.persisted || !saved.operation_id) {
    throw new ApiError(502, { code: 'PERSIST_FAILED', detail: 'Plan was not persisted' });
  }
  return regenerated ? { operationId: saved.operation_id, regenerated } : { operationId: saved.operation_id };
}
