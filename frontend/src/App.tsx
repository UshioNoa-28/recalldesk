import React, { useState, useEffect, useCallback } from 'react';
import { ActiveView, TargetChunkLink } from './types';
import { api } from './api/client';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/Common/TopBar';
import { QueryConsole } from './components/Search/QueryConsole';
import { DocumentExplorer } from './components/Documents/DocumentExplorer';
import { EvaluationStudio } from './components/Evaluation/EvaluationStudio';
import { DocumentUploadModal } from './components/Documents/DocumentUploadModal';
import { SettingsModal } from './components/Common/SettingsModal';
import { ToastProvider } from './context/ToastContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginPage } from './components/Auth/LoginPage';
import { RegisterPage } from './components/Auth/RegisterPage';
import { Loader2 } from 'lucide-react';

const AppContent: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();

  const [activeView, setActiveView] = useState<ActiveView>('search');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [targetChunk, setTargetChunk] = useState<TargetChunkLink | null>(null);
  const [documentCount, setDocumentCount] = useState(0);
  const [testSetCount, setTestSetCount] = useState(0);
  const [selectedTestSetId, setSelectedTestSetId] = useState<string | null>(null);

  const fetchDocCount = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const res = await api.listDocuments(1, 1);
      setDocumentCount(res.total || 0);
    } catch {
      // Ignore
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchDocCount();
      const timer = setInterval(() => {
        fetchDocCount();
      }, 15000);
      return () => clearInterval(timer);
    }
  }, [isAuthenticated, fetchDocCount]);

  // Handle URL hash changes
  const parseHash = useCallback(() => {
    const hash = window.location.hash;

    if (hash === '#/register') {
      setActiveView('register');
      return;
    }
    if (hash === '#/login') {
      setActiveView('login');
      return;
    }

    if (!isAuthenticated && !isLoading) {
      // Unauthenticated users visiting any page must be redirected to /login
      setActiveView('login');
      if (window.location.hash !== '#/login') {
        window.location.hash = '#/login';
      }
      return;
    }

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
        setTargetChunk((prev) => {
          if (prev?.documentId === docId && prev?.chunkIndex === chunkIndex) {
            return prev;
          }
          return { documentId: docId, chunkIndex };
        });
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
    } else {
      // Fallback
      if (isAuthenticated) {
        setActiveView('search');
      } else {
        setActiveView('login');
      }
    }
  }, [isAuthenticated, isLoading]);

  useEffect(() => {
    parseHash();
    window.addEventListener('hashchange', parseHash);
    return () => window.removeEventListener('hashchange', parseHash);
  }, [parseHash]);

  // When authentication status flips
  useEffect(() => {
    if (!isLoading) {
      if (!isAuthenticated) {
        if (window.location.hash !== '#/register') {
          window.location.hash = '#/login';
          setActiveView('login');
        }
      } else {
        if (window.location.hash === '#/login' || window.location.hash === '#/register') {
          window.location.hash = '#/search';
          setActiveView('search');
        }
      }
    }
  }, [isAuthenticated, isLoading]);

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
    if (view === 'evaluation') {
      setSelectedTestSetId(null);
    }
    window.location.hash = `#/${view}`;
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-slate-50 font-mono text-xs text-slate-500">
        <Loader2 className="w-7 h-7 animate-spin text-blue-600 mb-2.5" />
        <span>正在验证登录状态...</span>
      </div>
    );
  }

  // Unauthenticated: Show Login or Register page
  if (!isAuthenticated) {
    if (activeView === 'register') {
      return (
        <RegisterPage
          onNavigateToLogin={() => {
            setActiveView('login');
            window.location.hash = '#/login';
          }}
          onRegisterSuccess={() => {
            setActiveView('search');
            window.location.hash = '#/search';
          }}
        />
      );
    }
    return (
      <LoginPage
        onNavigateToRegister={() => {
          setActiveView('register');
          window.location.hash = '#/register';
        }}
        onLoginSuccess={() => {
          setActiveView('search');
          window.location.hash = '#/search';
        }}
      />
    );
  }

  // Authenticated Main Workspace Layout
  return (
    <div className="h-screen w-screen flex bg-slate-50 text-slate-900 overflow-hidden font-sans">
      {/* Left Sidebar */}
      <Sidebar
        activeView={activeView}
        setActiveView={handleSidebarViewChange}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenUpload={() => setIsUploadOpen(true)}
        documentCount={documentCount}
        evalQuestionCount={testSetCount}
      />

      {/* Main Workspace Area with TopBar */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
        <TopBar
          activeView={activeView}
          onOpenSettings={() => setIsSettingsOpen(true)}
        />

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
                window.location.hash = '#/search';
              }}
              refreshTrigger={refreshTrigger}
            />
          ) : (
            <EvaluationStudio
              selectedTestSetId={selectedTestSetId}
              onNavigateToChunk={handleNavigateToChunk}
              onUpdateTestSetCount={(count) => setTestSetCount(count)}
            />
          )}
        </main>
      </div>

      {/* Upload Modal */}
      <DocumentUploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onUploadSuccess={() => {
          setRefreshTrigger((prev) => prev + 1);
          fetchDocCount();
        }}
      />

      {/* Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onSaved={() => {
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
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </ToastProvider>
  );
};

export default App;
