"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

interface FileItem {
  name: string;
  path: string;
  type: "file" | "folder";
  size?: number;
  modified?: string;
  children?: number;
}

interface UploadState {
  name: string;
  progress: number; // 0-100
  status: "uploading" | "done" | "error" | "duplicate";
  size: number;
}

export default function FilesPage() {
  const [currentPath, setCurrentPath] = useState("");
  const [items, setItems] = useState<FileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchFiles();
  }, [currentPath]);

  async function fetchFiles() {
    setLoading(true);
    try {
      const res = await fetch(`/api/proxy/files?path=${encodeURIComponent(currentPath)}`);
      if (res.ok) {
        const data = await res.json();
        setItems(Array.isArray(data.items) ? data.items : []);
      }
    } catch (err) {
      console.error("Failed to list files:", err);
    }
    setLoading(false);
  }

  async function handleUpload(files: FileList | null) {
    if (!files || files.length === 0) return;

    const existingNames = new Set(items.filter((i) => i.type === "file").map((i) => i.name));

    for (const file of Array.from(files)) {
      // Check for duplicate
      if (existingNames.has(file.name)) {
        setUploads((prev) => [...prev, {
          name: file.name, progress: 0, status: "duplicate", size: file.size,
        }]);
        continue;
      }

      // Check if already uploading this file
      if (uploads.some((u) => u.name === file.name && u.status === "uploading")) {
        continue;
      }

      // Add to upload queue
      setUploads((prev) => [...prev, {
        name: file.name, progress: 0, status: "uploading", size: file.size,
      }]);

      // Chunked upload: 8MB chunks to avoid proxy/memory limits
      const CHUNK_SIZE = 8 * 1024 * 1024;
      const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

      try {
        for (let chunkIdx = 0; chunkIdx < totalChunks; chunkIdx++) {
          const start = chunkIdx * CHUNK_SIZE;
          const end = Math.min(start + CHUNK_SIZE, file.size);
          const chunk = file.slice(start, end);

          const formData = new FormData();
          formData.append("file", chunk, file.name);

          const params = new URLSearchParams({
            path: currentPath,
            chunk_index: String(chunkIdx),
            total_chunks: String(totalChunks),
            original_size: String(file.size),
          });

          const res = await fetch(`/api/proxy/files/upload?${params}`, {
            method: "POST", body: formData,
          });

          if (!res.ok) throw new Error(`Chunk ${chunkIdx + 1} failed: ${res.status}`);

          const pct = Math.round(((chunkIdx + 1) / totalChunks) * 100);
          setUploads((prev) => prev.map((u) =>
            u.name === file.name && u.status === "uploading" ? { ...u, progress: pct } : u
          ));
        }

        setUploads((prev) => prev.map((u) =>
          u.name === file.name && u.status === "uploading" ? { ...u, progress: 100, status: "done" } : u
        ));
        fetchFiles();
      } catch (err) {
        console.error(`Upload failed for ${file.name}:`, err);
        setUploads((prev) => prev.map((u) =>
          u.name === file.name && u.status === "uploading" ? { ...u, status: "error" } : u
        ));
      }
    }
  }

  function clearUploads() {
    setUploads((prev) => prev.filter((u) => u.status === "uploading"));
  }

  async function handleCreateFolder() {
    if (!newFolderName.trim()) return;
    try {
      await fetch(`/api/proxy/files/folder?name=${encodeURIComponent(newFolderName)}&path=${encodeURIComponent(currentPath)}`, {
        method: "POST",
      });
      setNewFolderName("");
      setShowNewFolder(false);
      fetchFiles();
    } catch (err) {
      console.error("Create folder failed:", err);
    }
  }

  async function handleDelete(item: FileItem) {
    if (!confirm(`Delete "${item.name}"${item.type === "folder" ? " and all contents" : ""}?`)) return;
    try {
      await fetch(`/api/proxy/files?path=${encodeURIComponent(item.path)}`, { method: "DELETE" });
      fetchFiles();
    } catch (err) {
      console.error("Delete failed:", err);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    handleUpload(e.dataTransfer.files);
  }

  function navigateUp() {
    const parts = currentPath.split("/").filter(Boolean);
    parts.pop();
    setCurrentPath(parts.join("/"));
  }

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  const breadcrumbs = ["Files", ...currentPath.split("/").filter(Boolean)];
  const activeUploads = uploads.filter((u) => u.status === "uploading");
  const finishedUploads = uploads.filter((u) => u.status !== "uploading");

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-3 md:px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Link href="/" className="text-gray-400 hover:text-white text-sm shrink-0">&larr;</Link>
          <h1 className="text-base md:text-lg font-bold">File Manager</h1>
        </div>
        <div className="flex gap-2">
          <Link href="/ops" className="text-gray-500 hover:text-white text-xs">Ops</Link>
        </div>
      </header>

      <div className="px-3 md:px-6 py-4 max-w-5xl">
        {/* Breadcrumbs */}
        <div className="flex items-center gap-1 mb-4 text-sm flex-wrap">
          {breadcrumbs.map((crumb, i) => {
            const path = breadcrumbs.slice(1, i + 1).join("/");
            const isLast = i === breadcrumbs.length - 1;
            return (
              <span key={i} className="flex items-center gap-1">
                {i > 0 && <span className="text-gray-700">/</span>}
                {isLast ? (
                  <span className="text-white font-medium">{crumb}</span>
                ) : (
                  <button onClick={() => setCurrentPath(i === 0 ? "" : path)}
                    className="text-blue-400 hover:text-blue-300">{crumb}</button>
                )}
              </span>
            );
          })}
        </div>

        {/* Toolbar */}
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          {currentPath && (
            <button onClick={navigateUp}
              className="bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs px-3 py-2 rounded">
              &larr; Up
            </button>
          )}
          <button onClick={() => setShowNewFolder(!showNewFolder)}
            className="bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs px-3 py-2 rounded">
            + New Folder
          </button>
          <button onClick={() => fileInputRef.current?.click()}
            disabled={activeUploads.length > 0}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs px-3 py-2 rounded font-medium">
            {activeUploads.length > 0 ? `Uploading (${activeUploads.length})...` : "Upload Files"}
          </button>
          <input ref={fileInputRef} type="file" multiple className="hidden"
            onChange={(e) => { handleUpload(e.target.files); e.target.value = ""; }} />
          <button onClick={fetchFiles}
            className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-2 rounded ml-auto">
            Refresh
          </button>
        </div>

        {/* Upload progress */}
        {uploads.length > 0 && (
          <div className="mb-4 space-y-1.5">
            {uploads.map((u, i) => (
              <div key={`${u.name}-${i}`} className={`rounded-lg px-3 py-2 text-xs flex items-center gap-3 ${
                u.status === "uploading" ? "bg-blue-950/40 border border-blue-800" :
                u.status === "done" ? "bg-green-950/40 border border-green-800" :
                u.status === "duplicate" ? "bg-amber-950/40 border border-amber-800" :
                "bg-red-950/40 border border-red-800"
              }`}>
                <span className="truncate flex-1 font-medium">{u.name}</span>
                <span className="text-gray-500 shrink-0">{formatSize(u.size)}</span>
                {u.status === "uploading" && (
                  <div className="w-32 shrink-0">
                    <div className="bg-gray-800 rounded-full h-1.5 overflow-hidden">
                      <div className="bg-blue-500 h-full rounded-full transition-all duration-300"
                        style={{ width: `${u.progress}%` }} />
                    </div>
                    <span className="text-blue-300 text-[10px]">{u.progress}%</span>
                  </div>
                )}
                {u.status === "done" && <span className="text-green-400 shrink-0">Done</span>}
                {u.status === "error" && <span className="text-red-400 shrink-0">Failed</span>}
                {u.status === "duplicate" && <span className="text-amber-400 shrink-0">Already exists</span>}
              </div>
            ))}
            {finishedUploads.length > 0 && (
              <button onClick={clearUploads}
                className="text-gray-600 hover:text-gray-400 text-xs">
                Clear completed
              </button>
            )}
          </div>
        )}

        {/* New folder input */}
        {showNewFolder && (
          <div className="flex gap-2 mb-4">
            <input type="text" value={newFolderName} onChange={(e) => setNewFolderName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreateFolder()}
              placeholder="Folder name..."
              className="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-white" autoFocus />
            <button onClick={handleCreateFolder}
              className="bg-green-700 hover:bg-green-600 text-white text-xs px-4 py-2 rounded font-medium">Create</button>
            <button onClick={() => { setShowNewFolder(false); setNewFolderName(""); }}
              className="bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs px-3 py-2 rounded">Cancel</button>
          </div>
        )}

        {/* Drop zone + file list */}
        <div
          className={`bg-gray-900 border rounded-lg overflow-hidden transition-colors relative ${
            dragOver ? "border-blue-500 bg-blue-950/20" : "border-gray-800"
          }`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          {loading ? (
            <div className="text-gray-600 text-sm text-center py-12">Loading...</div>
          ) : items.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-gray-600 text-sm mb-2">This folder is empty</p>
              <p className="text-gray-700 text-xs">Drag & drop files here or click Upload</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500 text-xs">
                  <th className="text-left px-4 py-2.5">Name</th>
                  <th className="text-right px-4 py-2.5 hidden sm:table-cell">Size</th>
                  <th className="text-right px-4 py-2.5 hidden md:table-cell">Modified</th>
                  <th className="text-right px-4 py-2.5 w-20"></th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.path}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30 group cursor-pointer"
                    onClick={() => item.type === "folder" ? setCurrentPath(item.path) : undefined}>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        {item.type === "folder" ? (
                          <span className="text-yellow-500 text-base">&#128193;</span>
                        ) : (
                          <span className="text-gray-500 text-base">&#128196;</span>
                        )}
                        <span className={`${item.type === "folder" ? "text-white font-medium" : "text-gray-300"}`}>
                          {item.name}
                        </span>
                        {item.type === "folder" && item.children != null && (
                          <span className="text-gray-600 text-xs">({item.children})</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-500 text-xs hidden sm:table-cell">
                      {item.type === "file" && item.size != null ? formatSize(item.size) : ""}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-600 text-xs hidden md:table-cell">
                      {item.modified ? new Date(item.modified).toLocaleDateString() : ""}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="flex gap-1 justify-end opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                        {item.type === "file" && (
                          <a href={`/api/proxy/files/download?path=${encodeURIComponent(item.path)}`}
                            className="text-blue-400 hover:text-blue-300 text-xs px-2 py-1 rounded bg-gray-800"
                            download>DL</a>
                        )}
                        <button onClick={() => handleDelete(item)}
                          className="text-red-400 hover:text-red-300 text-xs px-2 py-1 rounded bg-gray-800">
                          Del
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Drop overlay */}
          {dragOver && (
            <div className="absolute inset-0 flex items-center justify-center bg-blue-950/60 z-10">
              <p className="text-blue-300 text-lg font-medium">Drop files to upload</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
