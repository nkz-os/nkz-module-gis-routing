export type SlotType =
  | 'entity-tree'
  | 'map-layer'
  | 'context-panel'
  | 'bottom-panel'
  | 'layer-toggle'
  | 'dashboard-widget';

export interface SlotWidgetDefinition {
  id: string;
  moduleId: string;
  component: string;
  priority?: number;
  showWhen?: any;
  defaultProps?: Record<string, any>;
  localComponent?: unknown;
}

export interface ModuleViewerSlots {
  'entity-tree'?: SlotWidgetDefinition[];
  'map-layer'?: SlotWidgetDefinition[];
  'context-panel'?: SlotWidgetDefinition[];
  'bottom-panel'?: SlotWidgetDefinition[];
  'layer-toggle'?: SlotWidgetDefinition[];
  'dashboard-widget'?: SlotWidgetDefinition[];
}
