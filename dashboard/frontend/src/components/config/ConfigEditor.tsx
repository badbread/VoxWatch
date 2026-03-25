/**
 * ConfigEditor — main config page with vertical tab navigation and save bar.
 *
 * Loads the current config via React Query, tracks local edits in component
 * state, runs client-side validation on every change, and commits via the
 * save mutation. The ConfigSaveBar slides up from the bottom when the form
 * is dirty.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Server,
  Radio,
  Camera,
  Clock,
  Brain,
  Layers,
  Mic,
  // Volume2 removed — Audio Output section removed
  FileText,
  Theater,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { Card } from '@/components/common/Card';
import { PageSpinner } from '@/components/common/LoadingSpinner';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { ConfigSaveBar } from './ConfigSaveBar';
import { FrigateConfigForm } from './FrigateConfigForm';
import { Go2rtcConfigForm } from './Go2rtcConfigForm';
import { CamerasConfigForm } from './CamerasConfigForm';
import { ConditionsConfigForm } from './ConditionsConfigForm';
import { AiConfigForm } from './AiConfigForm';
import { StagesConfigForm } from './StagesConfigForm';
import { TtsConfigForm } from './TtsConfigForm';
// AudioConfigForm removed — codec settings are per-camera now
import { LoggingConfigForm } from './LoggingConfigForm';
import { PersonaConfigForm } from './PersonaConfigForm';
import { useConfigQuery, useConfigMutation } from '@/hooks/useConfig';
import { validateConfig } from '@/utils/validators';
import type { VoxWatchConfig } from '@/types/config';

interface TabDef {
  id: string;
  label: string;
  icon: React.ElementType;
  section: keyof VoxWatchConfig | 'stages' | 'audio_combined' | 'response_mode';
}

const TABS: TabDef[] = [
  { id: 'services', label: 'Services', icon: Server, section: 'frigate' },
  { id: 'cameras', label: 'Cameras', icon: Camera, section: 'cameras' },
  { id: 'detection', label: 'Mode', icon: Clock, section: 'conditions' },
  { id: 'ai', label: 'AI Provider', icon: Brain, section: 'ai' },
  { id: 'pipeline', label: 'Pipeline', icon: Layers, section: 'stages' },
  { id: 'response_mode', label: 'TTS/Personality', icon: Theater, section: 'response_mode' },
  { id: 'logging', label: 'Logging', icon: FileText, section: 'logging' },
];

/**
 * Full configuration editor with tabbed sections and sticky save bar.
 */
export function ConfigEditor() {
  const { data: remoteConfig, isLoading } = useConfigQuery();
  const saveMutation = useConfigMutation();

  const [localConfig, setLocalConfig] = useState<VoxWatchConfig | null>(null);

  // Support ?tab=cameras query param for deep linking (e.g. from "Add to VoxWatch" button)
  const searchParams = new URLSearchParams(window.location.search);
  const initialTab = TABS.find((t) => t.id === searchParams.get('tab'))?.id ?? TABS[0]!.id;
  const [activeTab, setActiveTab] = useState(initialTab);
  const [isDirty, setIsDirty] = useState(false);

  // Seed local state from the fetched config
  useEffect(() => {
    if (remoteConfig && !isDirty) {
      setLocalConfig(remoteConfig);
    }
  }, [remoteConfig, isDirty]);

  const handleChange = useCallback(
    (patch: Partial<VoxWatchConfig>) => {
      setLocalConfig((prev) => {
        if (!prev) return prev;
        return { ...prev, ...patch };
      });
      setIsDirty(true);
    },
    [],
  );

  const validationResult = localConfig
    ? validateConfig(localConfig)
    : { valid: false, errors: [] };

  const handleSave = () => {
    if (!localConfig) return;
    saveMutation.mutate(localConfig, {
      onSuccess: () => setIsDirty(false),
    });
  };

  const handleDiscard = () => {
    if (remoteConfig) {
      setLocalConfig(remoteConfig);
      setIsDirty(false);
    }
  };

  if (isLoading || !localConfig) {
    return <PageSpinner />;
  }

  const activeTabDef = TABS.find((t) => t.id === activeTab);

  return (
    <div className="flex min-h-0 flex-col gap-4">
      <div className="flex gap-4">
        {/* Vertical tab list */}
        <nav
          aria-label="Configuration sections"
          className="hidden w-40 flex-shrink-0 sm:block lg:w-48"
        >
          <ul className="space-y-0.5">
            {TABS.map(({ id, label, icon: Icon }) => (
              <li key={id}>
                <button
                  onClick={() => setActiveTab(id)}
                  className={cn(
                    'flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                    activeTab === id
                      ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-400'
                      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100',
                  )}
                  aria-current={activeTab === id ? 'page' : undefined}
                >
                  <Icon className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        {/* Mobile tab selector */}
        <div className="sm:hidden">
          <select
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value)}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
          >
            {TABS.map(({ id, label }) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </div>

        {/* Form panel */}
        <div className="min-w-0 flex-1">
          <ErrorBoundary>
            <Card title={activeTabDef?.label} className="pb-20 sm:pb-6">
              {/* Services: Frigate + go2rtc */}
              {activeTab === 'services' && (
                <div className="space-y-6">
                  <div>
                    <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-200">
                      <Server className="h-4 w-4 text-blue-500" /> Frigate NVR
                    </h4>
                    <FrigateConfigForm
                      value={localConfig.frigate}
                      onChange={(frigate) => handleChange({ frigate })}
                      errors={validationResult.errors}
                    />
                  </div>
                  <hr className="border-gray-200 dark:border-gray-700" />
                  <div>
                    <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-200">
                      <Radio className="h-4 w-4 text-purple-500" /> go2rtc
                    </h4>
                    <Go2rtcConfigForm
                      value={localConfig.go2rtc}
                      onChange={(go2rtc) => handleChange({ go2rtc })}
                      errors={validationResult.errors}
                    />
                  </div>
                </div>
              )}
              {activeTab === 'cameras' && (
                <CamerasConfigForm
                  value={localConfig.cameras}
                  onChange={(cameras) => handleChange({ cameras })}
                  errors={validationResult.errors}
                />
              )}
              {activeTab === 'detection' && (
                <ConditionsConfigForm
                  value={localConfig.conditions}
                  onChange={(conditions) => handleChange({ conditions })}
                  errors={validationResult.errors}
                />
              )}
              {activeTab === 'ai' && (
                <AiConfigForm
                  value={localConfig.ai}
                  onChange={(ai) => handleChange({ ai })}
                  errors={validationResult.errors}
                />
              )}
              {/* Pipeline: Stages + TTS + Audio + Messages */}
              {activeTab === 'pipeline' && (
                <div className="space-y-6">
                  <StagesConfigForm
                    stage2={localConfig.stage2}
                    stage3={localConfig.stage3}
                    messages={localConfig.messages}
                    pipeline={localConfig.pipeline}
                    onStage2Change={(stage2) => handleChange({ stage2 })}
                    onStage3Change={(stage3) => handleChange({ stage3 })}
                    onMessagesChange={(messages) => handleChange({ messages })}
                    onPipelineChange={(pipeline) => handleChange({ pipeline })}
                    errors={validationResult.errors}
                  />
                  {/* Audio Output removed — codec/sample_rate/channels are per-camera settings */}
                </div>
              )}
              {activeTab === 'response_mode' && (
                <div className="space-y-6">
                  <div>
                    <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-200">
                      <Mic className="h-4 w-4 text-orange-500" /> Text-to-Speech
                    </h4>
                    <TtsConfigForm
                      value={localConfig.tts}
                      onChange={(tts) => handleChange({ tts })}
                      errors={validationResult.errors}
                      activePersona={
                        localConfig.response_mode?.name ??
                        localConfig.persona?.name ??
                        'standard'
                      }
                    />
                  </div>
                  <hr className="border-gray-200 dark:border-gray-700" />
                  <div>
                    <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-200">
                      <Theater className="h-4 w-4 text-purple-500" /> Response Mode
                    </h4>
                    <PersonaConfigForm
                      value={
                        localConfig.response_mode ??
                        localConfig.persona ?? { name: 'standard', custom_prompt: '' }
                      }
                      onChange={(response_mode) => handleChange({ response_mode })}
                      errors={validationResult.errors}
                      ttsConfig={localConfig.tts}
                    />
                  </div>
                </div>
              )}
              {activeTab === 'logging' && (
                <LoggingConfigForm
                  value={localConfig.logging}
                  onChange={(logging) => handleChange({ logging })}
                  errors={validationResult.errors}
                />
              )}
            </Card>
          </ErrorBoundary>
        </div>
      </div>

      {/* Sticky save bar */}
      <ConfigSaveBar
        isDirty={isDirty}
        isSaving={saveMutation.isPending}
        errors={validationResult.errors}
        originalConfig={remoteConfig ?? null}
        currentConfig={localConfig}
        onSave={handleSave}
        onDiscard={handleDiscard}
      />
    </div>
  );
}
