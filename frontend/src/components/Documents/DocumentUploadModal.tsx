import React, { useState, useRef } from 'react';
import { X, UploadCloud, FileText, Loader2 } from 'lucide-react';
import { api, formatErrorMessage } from '../../api/client';
import { useToast } from '../../context/ToastContext';

interface DocumentUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUploadSuccess: () => void;
}

const ALLOWED_EXTS = ['.txt', '.md', '.csv', '.json', '.pdf'];
const MAX_SIZE_MB = 10;

export const DocumentUploadModal: React.FC<DocumentUploadModalProps> = ({
  isOpen,
  onClose,
  onUploadSuccess,
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { addToast } = useToast();

  if (!isOpen) return null;

  const validateFile = (file: File): string | null => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!ALLOWED_EXTS.includes(ext)) {
      return `不支持的文件格式 (${ext})，仅支持：${ALLOWED_EXTS.join(', ')}`;
    }
    if (file.size === 0) {
      return '文件内容为空';
    }
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      return `文件大小超过 ${MAX_SIZE_MB}MB 限制`;
    }
    return null;
  };

  const handleUpload = async (file: File) => {
    const errorMsg = validateFile(file);
    if (errorMsg) {
      addToast('error', '文件校验失败', errorMsg);
      return;
    }

    setUploading(true);
    try {
      const res = await api.uploadDocument(file);
      addToast('success', '上传成功', `文档「${res.name}」已提交，后台正在解析与切片...`);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      onUploadSuccess();
      onClose();
    } catch (err) {
      addToast('error', '上传失败', formatErrorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      setSelectedFile(files[0]);
      handleUpload(files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      setSelectedFile(files[0]);
      handleUpload(files[0]);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
      <div className="bg-white border border-slate-200 rounded-xl max-w-lg w-full p-5 shadow-xl space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div className="flex items-center gap-2">
            <UploadCloud className="w-4 h-4 text-blue-600" />
            <h3 className="text-sm font-bold text-slate-900 font-mono">上传文档到知识库</h3>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 p-1 rounded hover:bg-slate-100 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Dropzone */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => !uploading && fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-7 text-center cursor-pointer flex flex-col items-center justify-center gap-3 transition-colors ${
            isDragging
              ? 'border-blue-500 bg-blue-50/50'
              : 'border-slate-300 hover:border-slate-400 bg-slate-50'
          } ${uploading ? 'opacity-70 pointer-events-none' : ''}`}
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept={ALLOWED_EXTS.join(',') + ',application/pdf'}
            className="hidden"
          />

          <div className="w-12 h-12 rounded-full bg-blue-50 border border-blue-100 flex items-center justify-center text-blue-600 shadow-2xs">
            {uploading ? (
              <Loader2 className="w-6 h-6 animate-spin text-blue-600" />
            ) : (
              <FileText className="w-6 h-6" />
            )}
          </div>

          <div className="space-y-1">
            <p className="text-xs font-semibold text-slate-800">
              {uploading && selectedFile
                ? `正在上传「${selectedFile.name}」(${formatFileSize(selectedFile.size)})...`
                : '点击选择或拖拽文件到此处'}
            </p>
            <p className="text-[11px] text-slate-500">
              单文件大小上限 10MB，支持常用文本与 PDF 文档
            </p>
          </div>

          {/* Supported format tags */}
          <div className="flex items-center justify-center gap-1.5 flex-wrap pt-1 font-mono text-[10px]">
            <span className="px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 font-bold">
              .pdf
            </span>
            <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 font-bold">
              .md
            </span>
            <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200 font-bold">
              .txt
            </span>
            <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-bold">
              .csv
            </span>
            <span className="px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-bold">
              .json
            </span>
          </div>
        </div>

        <div className="flex items-center justify-end pt-2 border-t border-slate-100">
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 text-xs text-slate-600 hover:bg-slate-100 rounded-lg font-medium cursor-pointer"
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
};
