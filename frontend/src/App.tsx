import React, { useState, useEffect, useCallback } from 'react';
import { ActiveView, HealthResponse, TargetChunkLink } from './types';
import { api } from './api/client';
import { Sidebar } from './components/Sidebar';
import { QueryConsole } from './components/Search/QueryConsole';
import { DocumentExplorer } from './components/Documents/DocumentExplorer';
import { EvaluationStudio } from './components/Evaluation/EvaluationStudio';
import { DocumentUploadModal } from './components/Documents/DocumentUploadModal';
import { SettingsModal } from './components/Common/SettingsModal';
import { ToastProvider } from './context/ToastContext';

const AppContent: React.FC = () => {
  const [activeView, setActiveView] = useState<ActiveView>('search');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [targetChunk, setTargetChunk] = useState<TargetChunkLink | null>(null);
  const [documentCount, setDocumentCount] = useState(0);
  const [testSetCount, setTestSetCount] = useState(0);
  const [selectedTestSetId, setSelectedTestSetId] = useState<string | null>(null);
  const [appendTargetTestSet, setAppendTargetTestSet] = useState<{ id: string; name: string } | null>(null);

  const checkHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const res = await api.getHealth();
      setHealth(res);
    } catch {
      setHealth(null);
    } finally {
      setHealthLoading(false);
    }
  }, []);

  const fetchDocCount = useCallback(async () => {
    try {
      const res = await api.listDocuments(1, 1);
      setDocumentCount(res.total || 0);
    } catch {
      // Ignore
    }
  }, []);

  useEffect(() => {
    checkHealth();
    fetchDocCount();
    const timer = setInterval(() => {
      checkHealth();
      fetchDocCount();
    }, 15000);
    return () => clearInterval(timer);
  }, [checkHealth, fetchDocCount]);

  // Handle URL hash changes
  const parseHash = useCallback(() => {
    const hash = window.location.hash;
    if (hash.startsWith('#/documents/')) {
      const parts = hash.replace('#/documents/', '').split('?');
      const docId = parts[0];
      let chunkIndex: number | undefined;
      if (parts[1]) {
        const params = new URLSearchParams(parts[1]);
        const chunkParam = params.get('chunk');
        if (chunkParam !== null && !isNaN(parseInt(chunkParam, 10))) {
          chunkIndex = parseInt(chunkParam, 10);
        }
      }
      if (docId && chunkIndex !== undefined) {
        setTargetChunk({ documentId: docId, chunkIndex });
      } else {
        setTargetChunk(null);
      }
      setActiveView('documents');
    } else if (hash === '#/documents') {
      setTargetChunk(null);
      setActiveView('documents');
    } else if (hash.startsWith('#/evaluation')) {
      setTargetChunk(null);
      const tsId = hash.replace('#/evaluation', '').replace(/^\/+/, '');
      setSelectedTestSetId(tsId || null);
      setActiveView('evaluation');
    } else if (hash.startsWith('#/search')) {
      setTargetChunk(null);
      setActiveView('search');
    }
  }, []);

  useEffect(() => {
    parseHash();
    window.addEventListener('hashchange', parseHash);
    return () => window.removeEventListener('hashchange', parseHash);
  }, [parseHash]);

  const handleNavigateToChunk = (target: TargetChunkLink) => {
    setTargetChunk(target);
    setActiveView('documents');
    window.location.hash = `#/documents/${target.documentId || ''}?chunk=${
      target.chunkIndex ?? 0
    }`;
  };

  const handleSidebarViewChange = (view: ActiveView) => {
    setActiveView(view);
    setTargetChunk(null);
    setAppendTargetTestSet(null);
    if (view === 'evaluation') {
      setSelectedTestSetId(null);
    }
    window.location.hash = `#/${view}`;
  };

  const handleTestSetCreated = (testsetId: string) => {
    setSelectedTestSetId(testsetId);
    setAppendTargetTestSet(null);
    setActiveView('evaluation');
    window.location.hash = `#/evaluation/${testsetId}`;
  };

  const handleStartAppendChunks = (ts: { id: string; name: string }) => {
    setAppendTargetTestSet(ts);
    setActiveView('documents');
    window.location.hash = '#/documents';
  };

  return (
    <div className="h-screen w-screen flex bg-slate-50 text-slate-900 overflow-hidden font-sans">
      {/* Left Vertical Sidebar */}
      <Sidebar
        activeView={activeView}
        setActiveView={handleSidebarViewChange}
        health={health}
        healthLoading={healthLoading}
        onRefreshHealth={checkHealth}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenUpload={() => setIsUploadOpen(true)}
        documentCount={documentCount}
        evalQuestionCount={testSetCount}
      />

      {/* Main Workspace Area */}
      <main className="flex-1 flex min-h-0 overflow-hidden">
        {activeView === 'search' ? (
          <QueryConsole onNavigateToChunk={handleNavigateToChunk} />
        ) : activeView === 'documents' ? (
          <DocumentExplorer
            initialTarget={targetChunk}
            onClearTarget={() => setTargetChunk(null)}
            onNavigateToSearch={() => {
              setActiveView('search');
              setTargetChunk(null);
              setAppendTargetTestSet(null);
              window.location.hash = '#/search';
            }}
            appendTargetTestSet={appendTargetTestSet}
            onClearAppendTarget={() => setAppendTargetTestSet(null)}
            onTestSetCreated={handleTestSetCreated}
            refreshTrigger={refreshTrigger}
          />
        ) : (
          <EvaluationStudio
            selectedTestSetId={selectedTestSetId}
            onNavigateToChunk={handleNavigateToChunk}
            onNavigateToExplorer={() => {
              setActiveView('documents');
              window.location.hash = '#/documents';
            }}
            onStartAppendChunks={handleStartAppendChunks}
            onUpdateTestSetCount={(count) => setTestSetCount(count)}
          />
        )}
      </main>

      {/* Upload Modal */}
      <DocumentUploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onUploadSuccess={() => {
          setRefreshTrigger((prev) => prev + 1);
          fetchDocCount();
          checkHealth();
        }}
      />

      {/* Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onSaved={() => {
          checkHealth();
          fetchDocCount();
          setRefreshTrigger((prev) => prev + 1);
        }}
      />
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  );
};

export default App;
