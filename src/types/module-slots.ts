import type React from 'react';

export type SlotType =
  | 'entity-tree'
  | 'map-layer'
  | 'context-panel'
  | 'bottom-panel'
  | 'layer-toggle'
  | 'dashboard-widget'
  | 'admin-tab';

export interface SlotWidgetDefinition {
  id: string;
  moduleId: string;
  component: string;
  localComponent?: React.ComponentType<any>;
  priority?: number;
  props?: Record<string, unknown>;
}

export type ModuleViewerSlots = Partial<Record<SlotType, SlotWidgetDefinition[]>>;
