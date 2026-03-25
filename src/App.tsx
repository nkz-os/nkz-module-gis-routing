/**
 * Standalone dev shell — only used by `npm run dev`.
 * In production the host loads nkz-module.js (IIFE) directly; this file is not bundled.
 */
import './i18n';
import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import './index.css';

const App: React.FC = () => {
  const { t } = useTranslation('template');
  return (
    <div className="w-full min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-lg shadow p-8 max-w-md w-full">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">{t('dev.title')}</h1>
        <p className="text-sm text-gray-500 mb-4">{t('dev.shellNote')}</p>
        <div className="bg-blue-50 border border-blue-200 rounded p-3 text-sm text-blue-800">
          {t('dev.buildInstructions', { cmd: 'npm run build:module', out: 'dist/nkz-module.js' })}
        </div>
      </div>
    </div>
  );
};

export default App;
