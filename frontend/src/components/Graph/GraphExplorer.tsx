import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Search,
  RotateCcw,
  ExternalLink,
  BookOpen,
  HelpCircle,
  Layers,
  FileText,
  RefreshCw,
  Compass,
  Database,
  X,
} from 'lucide-react';
import { api } from '../../api/client';
import {
  GraphEntityCard,
  TargetChunkLink,
} from '../../types';

interface GraphExplorerProps {
  onNavigateToChunk?: (target: TargetChunkLink) => void;
  initialEntity?: string | null;
}

interface CanvasNode {
  name_norm: string;
  name: string;
  type: string;
  x: number;
  y: number;
  radius: number;
  color: string;
  depth: number;
  expanded: boolean;
  isRoot: boolean;
  evidence_count: number;
  expandedBy?: string; // 记录该节点是由哪个节点展开引入的
}

interface CanvasLink {
  id: string;
  source: string;
  target: string;
  type: string;
  evidence: string[]; // ["doc_id:chunk_index", ...]
}

const TYPE_COLORS: Record<string, string> = {
  化学成分: '#2563eb', // 蓝
  物质: '#2563eb',
  产品: '#b45309', // 棕
  原料饮品: '#b45309',
  特征氨基酸: '#059669', // 绿
  生理受体: '#0891b2', // 青
  神经递质: '#0284c7',
  生理病理: '#7c3aed', // 紫
  中毒危象: '#dc2626', // 红
  处方抗生素: '#dc2626',
  药品: '#dc2626',
  代谢酶: '#0284c7',
  限速代谢酶: '#0284c7',
  默认: '#3b82f6',
};

const getColorForType = (type: string): string => {
  return TYPE_COLORS[type] || TYPE_COLORS['默认'];
};

export const GraphExplorer: React.FC<GraphExplorerProps> = ({
  onNavigateToChunk,
  initialEntity,
}) => {
  // 搜索与输入状态
  const [searchQuery, setSearchQuery] = useState('');
  const [searchCandidates, setSearchCandidates] = useState<GraphEntityCard[]>([]);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isSearching, setIsSearching] = useState(false);

  // 图谱浏览核心状态
  const [currentRoot, setCurrentRoot] = useState<string | null>(initialEntity || null);
  const [expandedSet, setExpandedSet] = useState<Set<string>>(new Set());
  const [limit, setLimit] = useState<number>(8);
  const [debouncedLimit, setDebouncedLimit] = useState<number>(8);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedLimit(limit);
    }, 250);
    return () => clearTimeout(timer);
  }, [limit]);
  const [suggestedSeeds, setSuggestedSeeds] = useState<GraphEntityCard[]>([]);

  // 选中的边或节点（用于右侧抽屉展示证据）
  const [selectedLink, setSelectedLink] = useState<CanvasLink | null>(null);
  const [selectedNodeName, setSelectedNodeName] = useState<string | null>(null);

  // 画布图数据
  const [nodes, setNodes] = useState<CanvasNode[]>([]);
  const [links, setLinks] = useState<CanvasLink[]>([]);

  // 切片缓存：doc_id -> chunks
  const chunkCacheRef = useRef<Map<string, Array<{ chunk_index: number; text: string }>>>(new Map());
  const [resolvedEvidences, setResolvedEvidences] = useState<
    Array<{
      docId: string;
      chunkIndex: number;
      text?: string;
      loading: boolean;
    }>
  >([]);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const nodesRef = useRef<CanvasNode[]>([]);
  const linksRef = useRef<CanvasLink[]>([]);

  // 保持 ref 实时同步以供事件监听器读取
  nodesRef.current = nodes;
  linksRef.current = links;

  // 拖拽与点击防抖控制
  const draggedNodeRef = useRef<CanvasNode | null>(null);
  const dragStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const hasDraggedRef = useRef<boolean>(false);
  const clickTimerRef = useRef<number | null>(null);

  // ==========================================
  // 1. 初始化图谱：中心根节点 + 1 跳环形排列 (位置永久固定)
  // ==========================================

  const initGraph = useCallback(
    async (rootNorm: string, targetLimit: number) => {
      setIsLoading(true);
      try {
        const data = await api.getEntityNeighborhood(rootNorm, 1, targetLimit);
        const rawNodes = data.nodes || [];
        const rawEdges = data.edges || [];

        if (rawNodes.length === 0) {
          setNodes([]);
          setLinks([]);
          try {
            const seedRes = await api.searchEntities('', 12);
            setSuggestedSeeds(seedRes.results || []);
          } catch {
            // ignore
          }
          return;
        }

        const width = canvasRef.current ? canvasRef.current.clientWidth : 800;
        const height = canvasRef.current ? canvasRef.current.clientHeight : 600;
        const cx = width / 2;
        const cy = height / 2;

        const rootNode = rawNodes.find((n) => n.hops === 0) || rawNodes[0];
        const hop1Nodes = rawNodes.filter(
          (n) => n.hops > 0 || n.name_norm !== rootNode.name_norm
        );

        const initialNodes: CanvasNode[] = [];

        // 根节点：锁定在画布中心
        initialNodes.push({
          name_norm: rootNode.name_norm,
          name: rootNode.name,
          type: rootNode.type,
          x: cx,
          y: cy,
          radius: 24,
          color: getColorForType(rootNode.type),
          depth: 0,
          expanded: false,
          isRoot: true,
          evidence_count: rootNode.evidence_count,
        });

        // 1跳邻居：环形均匀铺开，坐标固定
        const radius1 = 160;
        const count = hop1Nodes.length;
        hop1Nodes.forEach((n, idx) => {
          const angle = (idx / Math.max(1, count)) * Math.PI * 2 - Math.PI / 2;
          initialNodes.push({
            name_norm: n.name_norm,
            name: n.name,
            type: n.type,
            x: cx + Math.cos(angle) * radius1,
            y: cy + Math.sin(angle) * radius1,
            radius: 20,
            color: getColorForType(n.type),
            depth: 1,
            expanded: false,
            isRoot: false,
            evidence_count: n.evidence_count,
            expandedBy: rootNode.name_norm,
          });
        });

        // 边
        const initialLinks: CanvasLink[] = rawEdges.map((e, idx) => ({
          id: `edge_${idx}_${e.src}_${e.dst}_${e.type}`,
          source: e.src,
          target: e.dst,
          type: e.type,
          evidence: e.evidence || [],
        }));

        setNodes(initialNodes);
        setLinks(initialLinks);
        setExpandedSet(new Set());
        setSelectedNodeName(null);
        setSelectedLink(null);
      } catch (err) {
        console.error('初始化知识图谱失败:', err);
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  // 增量同步邻域上限：绝不重置中心实体坐标，绝不销毁已展开分支
  const syncNeighborhoodLimit = useCallback(
    async (targetLimit: number) => {
      const currentNodes = nodesRef.current;
      const rootNode = currentNodes.find((n) => n.isRoot);
      if (!rootNode) return;

      try {
        const data = await api.getEntityNeighborhood(rootNode.name_norm, 1, targetLimit);
        const rawNodes = data.nodes || [];
        const rawEdges = data.edges || [];

        const existingMap = new Map(currentNodes.map((n) => [n.name_norm, n]));
        const rootNorm = rootNode.name_norm;

        // 严格锁定根节点坐标（用户拖拽过或现有位置绝对不动）
        const cx = rootNode.x;
        const cy = rootNode.y;

        const newHop1Nodes = rawNodes.filter(
          (n) => n.name_norm !== rootNorm && (n.hops > 0 || !existingMap.has(n.name_norm))
        );
        const newHop1Norms = new Set(newHop1Nodes.map((n) => n.name_norm));

        // 保留节点集合：
        // 1. 根节点（原位）
        // 2. 所有已被展开过或深度 > 1 的分支节点（原位，绝不销毁分支）
        // 3. 仍在 newHop1Norms 中的 1 跳节点（原位）
        const nodesToKeep: CanvasNode[] = [];
        currentNodes.forEach((n) => {
          if (n.isRoot) {
            nodesToKeep.push(n);
          } else if (expandedSet.has(n.name_norm) || n.depth > 1) {
            nodesToKeep.push(n);
          } else if (n.depth === 1 && newHop1Norms.has(n.name_norm)) {
            nodesToKeep.push(n);
          }
        });

        const keptMap = new Map(nodesToKeep.map((n) => [n.name_norm, n]));

        // 需要新加入的 1 跳节点（滑块调大时产生）
        const candidateNodes = newHop1Nodes.filter((n) => !keptMap.has(n.name_norm));
        const nodesToAdd: CanvasNode[] = [];
        const radius1 = 160;

        // 收集已被占用的角度，避免新节点重叠
        const occupiedAngles = nodesToKeep
          .filter((n) => n.depth === 1)
          .map((n) => Math.atan2(n.y - cy, n.x - cx));

        candidateNodes.forEach((n, idx) => {
          let angle = (idx / Math.max(1, candidateNodes.length)) * Math.PI * 2 - Math.PI / 2;
          let attempts = 0;
          while (occupiedAngles.some((oa) => Math.abs(oa - angle) < 0.25) && attempts < 16) {
            angle += 0.35;
            attempts++;
          }
          occupiedAngles.push(angle);

          nodesToAdd.push({
            name_norm: n.name_norm,
            name: n.name,
            type: n.type,
            x: cx + Math.cos(angle) * radius1,
            y: cy + Math.sin(angle) * radius1,
            radius: 20,
            color: getColorForType(n.type),
            depth: 1,
            expanded: false,
            isRoot: false,
            evidence_count: n.evidence_count,
            expandedBy: rootNorm,
          });
        });

        const nextNodes = [...nodesToKeep, ...nodesToAdd];
        const nextNorms = new Set(nextNodes.map((n) => n.name_norm));

        // 同步边：两端都在 nextNorms 的边保留，并补充新邻居与图内节点的边
        const existingLinkMap = new Map(linksRef.current.map((l) => [l.id, l]));
        const nextLinks: CanvasLink[] = [];

        linksRef.current.forEach((l) => {
          if (nextNorms.has(l.source) && nextNorms.has(l.target)) {
            nextLinks.push(l);
          }
        });

        rawEdges.forEach((e, idx) => {
          const id = `edge_${idx}_${e.src}_${e.dst}_${e.type}`;
          if (nextNorms.has(e.src) && nextNorms.has(e.dst) && !existingLinkMap.has(id)) {
            nextLinks.push({
              id,
              source: e.src,
              target: e.dst,
              type: e.type,
              evidence: e.evidence || [],
            });
          }
        });

        setNodes(nextNodes);
        setLinks(nextLinks);
      } catch (err) {
        console.error('同步邻域上限失败:', err);
      }
    },
    [expandedSet]
  );

  const isInitialMount = useRef(true);
  const currentRootRef = useRef<string | null>(currentRoot);

  // 1) 初始加载或切换中心实体时初始化整张图谱
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      if (initialEntity) {
        currentRootRef.current = initialEntity;
        initGraph(initialEntity, limit);
      } else {
        // 未指定初始实体：拉取库中实体推荐供用户自主选择，不默认选定任何实体
        setIsLoading(true);
        api
          .searchEntities('', 12)
          .then((seedRes) => {
            const seeds = seedRes.results || [];
            setSuggestedSeeds(seeds);
          })
          .catch(() => {})
          .finally(() => setIsLoading(false));
      }
      return;
    }
    if (currentRoot && currentRootRef.current !== currentRoot) {
      currentRootRef.current = currentRoot;
      initGraph(currentRoot, limit);
    }
  }, [currentRoot, limit, initialEntity, initGraph]);

  // 2) 调节最大邻域数滑块：平滑增量同步，原位保留中心与已展开的分支
  useEffect(() => {
    if (isInitialMount.current) return;
    syncNeighborhoodLimit(debouncedLimit);
  }, [debouncedLimit, syncNeighborhoodLimit]);

  // ==========================================
  // 2. 拓展节点 (Expand)：仅给新节点定坐标，现有节点绝对不动 (Pinned)!
  // ==========================================

  const expandNode = async (nodeNameNorm: string) => {
    const currentNodes = nodesRef.current;
    const parent = currentNodes.find((n) => n.name_norm === nodeNameNorm);
    if (!parent) return;

    setIsLoading(true);
    try {
      // 查询被点击节点的 1 跳邻域
      const data = await api.getEntityNeighborhood(nodeNameNorm, 1, limit);
      const rawNodes = data.nodes || [];
      const rawEdges = data.edges || [];

      const existingMap = new Map(currentNodes.map((n) => [n.name_norm, n]));

      // 仅筛选画布上尚不存在的新节点
      const newRawNodes = rawNodes.filter(
        (rn) => !existingMap.has(rn.name_norm) && rn.name_norm !== nodeNameNorm
      );

      // 收集关联边（两端在已有或新节点中的）
      const currentLinks = linksRef.current;
      const existingLinkIds = new Set(currentLinks.map((l) => l.id));
      const newCanvasLinks: CanvasLink[] = [];

      rawEdges.forEach((e) => {
        const id = `edge_${e.src}_${e.dst}_${e.type}`;
        if (!existingLinkIds.has(id)) {
          newCanvasLinks.push({
            id,
            source: e.src,
            target: e.dst,
            type: e.type,
            evidence: e.evidence || [],
          });
          existingLinkIds.add(id);
        }
      });

      if (newRawNodes.length === 0) {
        // 无新节点加入，只更新展开状态和连线
        const updatedNodes = currentNodes.map((n) =>
          n.name_norm === nodeNameNorm ? { ...n, expanded: true } : n
        );
        setNodes(updatedNodes);
        setLinks([...currentLinks, ...newCanvasLinks]);
        setExpandedSet((prev) => new Set(prev).add(nodeNameNorm));
        return;
      }

      // 计算新节点朝外辐射的基准角度（方向先验）
      const root = currentNodes.find((n) => n.isRoot) || parent;
      const dx = parent.x - root.x;
      const dy = parent.y - root.y;
      const baseAngle = dx === 0 && dy === 0 ? -Math.PI / 2 : Math.atan2(dy, dx);
      const branchRadius = 140;

      const count = newRawNodes.length;
      const spreadArc = Math.min(Math.PI * 0.75, Math.max(0.4, count * 0.35));

      const newCanvasNodes: CanvasNode[] = newRawNodes.map((rn, idx) => {
        let angle = baseAngle;
        if (count > 1) {
          angle = baseAngle - spreadArc / 2 + (idx / (count - 1)) * spreadArc;
        }
        const nx = parent.x + Math.cos(angle) * branchRadius;
        const ny = parent.y + Math.sin(angle) * branchRadius;

        return {
          name_norm: rn.name_norm,
          name: rn.name,
          type: rn.type,
          x: nx,
          y: ny,
          radius: 19,
          color: getColorForType(rn.type),
          depth: parent.depth + 1,
          expanded: false,
          isRoot: false,
          evidence_count: rn.evidence_count,
          expandedBy: parent.name_norm,
        };
      });

      // 局部防重叠松弛：仅微调 newCanvasNodes，所有现有已有节点绝对锁定不动！
      relaxNewNodesOnly(newCanvasNodes, currentNodes, parent, 25);

      // 更新节点列表
      const updatedNodes = currentNodes.map((n) =>
        n.name_norm === nodeNameNorm ? { ...n, expanded: true } : n
      );

      setNodes([...updatedNodes, ...newCanvasNodes]);
      setLinks([...currentLinks, ...newCanvasLinks]);
      setExpandedSet((prev) => new Set(prev).add(nodeNameNorm));
    } catch (err) {
      console.error('拓展节点失败:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // 局部微调松弛：已有节点 (existingNodes) 绝对锁定！只调整新节点以避开重叠
  const relaxNewNodesOnly = (
    newNodes: CanvasNode[],
    existingNodes: CanvasNode[],
    parent: CanvasNode,
    iterations: number
  ) => {
    if (newNodes.length === 0) return;

    for (let it = 0; it < iterations; it++) {
      // 1. 新节点彼此之间防重叠排斥
      for (let i = 0; i < newNodes.length; i++) {
        for (let j = i + 1; j < newNodes.length; j++) {
          const a = newNodes[i];
          const b = newNodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.hypot(dx, dy) || 1;
          const minDist = a.radius + b.radius + 36;
          if (dist < minDist) {
            const overlap = ((minDist - dist) / dist) * 0.25;
            a.x -= dx * overlap * 0.5;
            a.y -= dy * overlap * 0.5;
            b.x += dx * overlap * 0.5;
            b.y += dy * overlap * 0.5;
          }
        }
      }

      // 2. 新节点受到已有固定节点的排斥（新节点被推开，已有节点完全不动）
      for (const a of newNodes) {
        for (const fixed of existingNodes) {
          if (fixed.name_norm === parent.name_norm) continue;
          const dx = a.x - fixed.x;
          const dy = a.y - fixed.y;
          const dist = Math.hypot(dx, dy) || 1;
          const minDist = a.radius + fixed.radius + 32;
          if (dist < minDist) {
            const push = ((minDist - dist) / dist) * 0.25;
            a.x += dx * push;
            a.y += dy * push;
          }
        }
      }

      // 3. 新节点与父节点维持大致的臂长 (135~150px)
      for (const a of newNodes) {
        const dx = a.x - parent.x;
        const dy = a.y - parent.y;
        const dist = Math.hypot(dx, dy) || 1;
        const ideal = 140;
        if (Math.abs(dist - ideal) > 10) {
          const delta = ((dist - ideal) / dist) * 0.04;
          a.x -= dx * delta;
          a.y -= dy * delta;
        }
      }
    }
  };

  // ==========================================
  // 3. 收回节点 (Collapse)：仅移除下属分支，其余节点坐标零位移！
  // ==========================================

  const collapseNode = (nodeNameNorm: string) => {
    const currentNodes = nodesRef.current;
    const currentLinks = linksRef.current;

    // 递归找出由 nodeNameNorm 引入的所有下级子孙节点
    const toRemove = new Set<string>();
    const queue = [nodeNameNorm];

    while (queue.length > 0) {
      const parentId = queue.shift()!;
      currentNodes.forEach((n) => {
        if (n.expandedBy === parentId && !toRemove.has(n.name_norm)) {
          toRemove.add(n.name_norm);
          queue.push(n.name_norm);
        }
      });
    }

    // 保留未被移除的节点，坐标完全不变！
    const remainingNodes = currentNodes
      .filter((n) => !toRemove.has(n.name_norm))
      .map((n) => (n.name_norm === nodeNameNorm ? { ...n, expanded: false } : n));

    // 移除两端包含被删节点的连线
    const remainingLinks = currentLinks.filter(
      (l) => !toRemove.has(l.source) && !toRemove.has(l.target)
    );

    setNodes(remainingNodes);
    setLinks(remainingLinks);

    // 清理展开状态与面包屑
    setExpandedSet((prev) => {
      const next = new Set(prev);
      next.delete(nodeNameNorm);
      toRemove.forEach((rn) => next.delete(rn));
      return next;
    });
  };

  // 双击切换展开/收起
  const handleNodeDoubleClick = (nameNorm: string) => {
    if (expandedSet.has(nameNorm)) {
      collapseNode(nameNorm);
    } else {
      expandNode(nameNorm);
    }
  };

  // 全部收起
  const handleResetBranches = () => {
    const currentNodes = nodesRef.current;
    const currentLinks = linksRef.current;
    const baseNodes = currentNodes
      .filter((n) => n.depth <= 1)
      .map((n) => ({ ...n, expanded: false }));

    const baseNorms = new Set(baseNodes.map((n) => n.name_norm));
    const baseLinks = currentLinks.filter(
      (l) => baseNorms.has(l.source) && baseNorms.has(l.target)
    );

    setNodes(baseNodes);
    setLinks(baseLinks);
    setExpandedSet(new Set());
  };

  // ==========================================
  // 4. 搜索框自动补全候选（三路召回）
  // ==========================================

  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchCandidates([]);
      return;
    }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await api.searchEntities(searchQuery.trim(), 8);
        setSearchCandidates(res.results || []);
        setIsDropdownOpen(true);
      } catch {
        setSearchCandidates([]);
      } finally {
        setIsSearching(false);
      }
    }, 220);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const handleSelectCandidate = (ent: GraphEntityCard) => {
    setCurrentRoot(ent.name_norm);
    setIsDropdownOpen(false);
    setSearchQuery(ent.name);
  };

  const handleClearGraph = () => {
    setSearchQuery('');
    setCurrentRoot(null);
    currentRootRef.current = null;
    setNodes([]);
    setLinks([]);
    setSelectedNodeName(null);
    setSelectedLink(null);
    setExpandedSet(new Set());
  };

  // ==========================================
  // 5. 证据解析与 Chunk 文本回查
  // ==========================================

  useEffect(() => {
    if (!selectedLink || !selectedLink.evidence || selectedLink.evidence.length === 0) {
      setResolvedEvidences([]);
      return;
    }

    const coords = selectedLink.evidence.map((coord) => {
      const parts = coord.split(':');
      return {
        docId: parts[0],
        chunkIndex: parseInt(parts[1] || '0', 10),
      };
    });

    setResolvedEvidences(
      coords.map((c) => ({
        docId: c.docId,
        chunkIndex: c.chunkIndex,
        text: undefined,
        loading: true,
      }))
    );

    coords.forEach(async (c, index) => {
      try {
        let chunkList = chunkCacheRef.current.get(c.docId);
        if (!chunkList) {
          const res = await api.getDocumentChunks(c.docId);
          chunkList = res.chunks || [];
          chunkCacheRef.current.set(c.docId, chunkList);
        }
        const found = chunkList.find((ch) => ch.chunk_index === c.chunkIndex);
        setResolvedEvidences((prev) => {
          const next = [...prev];
          if (next[index]) {
            next[index] = {
              ...next[index],
              text: found ? found.text : '（暂无原文文本）',
              loading: false,
            };
          }
          return next;
        });
      } catch {
        setResolvedEvidences((prev) => {
          const next = [...prev];
          if (next[index]) {
            next[index] = {
              ...next[index],
              text: '（切片原文调取失败）',
              loading: false,
            };
          }
          return next;
        });
      }
    });
  }, [selectedLink]);

  // ==========================================
  // 6. Canvas 渲染与灵敏绘制
  // ==========================================

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width / (window.devicePixelRatio || 1);
    const height = canvas.height / (window.devicePixelRatio || 1);

    ctx.clearRect(0, 0, width, height);

    // 点阵背景
    ctx.fillStyle = '#f1f5f9';
    for (let x = 16; x < width; x += 28) {
      for (let y = 16; y < height; y += 28) {
        ctx.fillRect(x, y, 1.2, 1.2);
      }
    }

    const currentNodes = nodesRef.current;
    const currentLinks = linksRef.current;
    const nodeMap = new Map<string, CanvasNode>();
    currentNodes.forEach((n) => nodeMap.set(n.name_norm, n));

    // 1. 绘制连线
    currentLinks.forEach((link) => {
      const s = nodeMap.get(link.source);
      const t = nodeMap.get(link.target);
      if (!s || !t) return;

      const isSelected = selectedLink?.id === link.id;
      const evCount = link.evidence ? link.evidence.length : 1;
      const baseWidth = Math.min(5, 1.4 + (evCount - 1) * 1.2);
      const strokeWidth = isSelected ? baseWidth + 2 : baseWidth;
      const strokeColor = isSelected ? '#2563eb' : '#cbd5e1';

      ctx.save();
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = strokeWidth;
      if (isSelected) {
        ctx.shadowColor = 'rgba(37, 99, 235, 0.4)';
        ctx.shadowBlur = 8;
      }
      ctx.stroke();
      ctx.restore();

      // 箭头
      const angle = Math.atan2(t.y - s.y, t.x - s.x);
      const endX = t.x - Math.cos(angle) * (t.radius + 2);
      const endY = t.y - Math.sin(angle) * (t.radius + 2);
      const arrowLen = 7;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(endX, endY);
      ctx.lineTo(
        endX - arrowLen * Math.cos(angle - Math.PI / 7),
        endY - arrowLen * Math.sin(angle - Math.PI / 7)
      );
      ctx.lineTo(
        endX - arrowLen * Math.cos(angle + Math.PI / 7),
        endY - arrowLen * Math.sin(angle + Math.PI / 7)
      );
      ctx.closePath();
      ctx.fillStyle = strokeColor;
      ctx.fill();
      ctx.restore();

      // 边关系文字胶囊
      const midX = (s.x + t.x) / 2;
      const midY = (s.y + t.y) / 2;
      const text = `${link.type} (${evCount})`;
      ctx.font = '11px sans-serif';
      const textW = ctx.measureText(text).width;
      const w = textW + 12;
      const h = 19;

      ctx.beginPath();
      ctx.roundRect(midX - w / 2, midY - h / 2, w, h, 9);
      ctx.fillStyle = isSelected ? '#eff6ff' : '#ffffff';
      ctx.fill();
      ctx.lineWidth = 1;
      ctx.strokeStyle = isSelected ? '#2563eb' : '#cbd5e1';
      ctx.stroke();

      ctx.fillStyle = isSelected ? '#1d4ed8' : '#475569';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, midX, midY);
    });

    // 2. 绘制节点
    currentNodes.forEach((node) => {
      const isSelected = selectedNodeName === node.name_norm;

      ctx.save();
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = node.color;
      ctx.shadowColor = 'rgba(0,0,0,0.06)';
      ctx.shadowBlur = 4;
      ctx.fill();

      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.strokeStyle = isSelected ? '#2563eb' : '#ffffff';
      ctx.stroke();
      ctx.restore();

      // 右上角展开状态角标 (+ / −)
      const isExp = node.expanded;
      const badgeX = node.x + node.radius * 0.72;
      const badgeY = node.y - node.radius * 0.72;
      ctx.beginPath();
      ctx.arc(badgeX, badgeY, 6.5, 0, Math.PI * 2);
      ctx.fillStyle = isExp ? '#dc2626' : '#2563eb';
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.2;
      ctx.stroke();

      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 9px monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(isExp ? '−' : '+', badgeX, badgeY);

      // 节点名称文字胶囊
      ctx.save();
      ctx.font = node.isRoot ? '600 12px sans-serif' : '500 12px sans-serif';
      const labelText = node.name;
      const textWidth = ctx.measureText(labelText).width;
      const tagY = node.y + node.radius + 6;

      ctx.fillStyle = isSelected ? '#eff6ff' : 'rgba(255, 255, 255, 0.95)';
      ctx.fillRect(node.x - textWidth / 2 - 6, tagY - 2, textWidth + 12, 18);
      ctx.strokeStyle = isSelected ? '#3b82f6' : '#e2e8f0';
      ctx.lineWidth = 1;
      ctx.strokeRect(node.x - textWidth / 2 - 6, tagY - 2, textWidth + 12, 18);

      ctx.fillStyle = isSelected ? '#1d4ed8' : '#1e293b';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(labelText, node.x, tagY + 7);
      ctx.restore();
    });
  }, [selectedLink, selectedNodeName]);

  useEffect(() => {
    draw();
  }, [nodes, links, draw]);

  useEffect(() => {
    const handleResize = () => {
      const canvas = canvasRef.current;
      const container = containerRef.current;
      if (!canvas || !container) return;
      const rect = container.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.resetTransform();
        ctx.scale(dpr, dpr);
      }
      draw();
    };

    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [draw]);

  // 命中检测：增大容差并根据实体名称长度动态匹配文字标签范围
  const getHitElement = (x: number, y: number) => {
    const currentNodes = nodesRef.current;
    const currentLinks = linksRef.current;

    for (let i = currentNodes.length - 1; i >= 0; i--) {
      const n = currentNodes[i];
      // 节点圆圈及外缘检测（加大至 radius + 10）
      if (Math.hypot(n.x - x, n.y - y) <= n.radius + 10) {
        return { type: 'node' as const, data: n };
      }
      // 实体名称文字胶囊检测（动态宽度，避免长中文实体名两侧点击失效）
      const tagY = n.y + n.radius + 6;
      const tagHalfW = Math.max(40, (n.name.length * 13) / 2 + 10);
      if (Math.abs(x - n.x) <= tagHalfW && y >= tagY - 6 && y <= tagY + 24) {
        return { type: 'node' as const, data: n };
      }
    }

    const nodeMap = new Map<string, CanvasNode>();
    currentNodes.forEach((n) => nodeMap.set(n.name_norm, n));

    for (const link of currentLinks) {
      const s = nodeMap.get(link.source);
      const t = nodeMap.get(link.target);
      if (!s || !t) continue;

      const midX = (s.x + t.x) / 2;
      const midY = (s.y + t.y) / 2;
      if (Math.abs(x - midX) <= 50 && Math.abs(y - midY) <= 15) {
        return { type: 'link' as const, data: link };
      }

      const l2 = (t.x - s.x) ** 2 + (t.y - s.y) ** 2;
      let d = 999;
      if (l2 === 0) {
        d = Math.hypot(x - s.x, y - s.y);
      } else {
        let param = ((x - s.x) * (t.x - s.x) + (y - s.y) * (t.y - s.y)) / l2;
        param = Math.max(0, Math.min(1, param));
        d = Math.hypot(x - (s.x + param * (t.x - s.x)), y - (s.y + param * (t.y - s.y)));
      }
      if (d <= 14) {
        return { type: 'link' as const, data: link };
      }
    }

    return null;
  };

  const handleCanvasMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    dragStartRef.current = { x, y };
    hasDraggedRef.current = false;

    const hit = getHitElement(x, y);
    if (hit && hit.type === 'node') {
      draggedNodeRef.current = hit.data;
    }
  };

  const handleCanvasMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    if (draggedNodeRef.current) {
      if (Math.hypot(x - dragStartRef.current.x, y - dragStartRef.current.y) > 10) {
        hasDraggedRef.current = true;
      }
      draggedNodeRef.current.x = x;
      draggedNodeRef.current.y = y;
      draw();
      e.currentTarget.style.cursor = 'grabbing';
      return;
    }

    const hit = getHitElement(x, y);
    e.currentTarget.style.cursor = hit ? 'pointer' : 'default';
  };

  const handleCanvasMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (hasDraggedRef.current && draggedNodeRef.current) {
      setNodes([...nodesRef.current]);
    }
    draggedNodeRef.current = null;
    const rect = e.currentTarget.getBoundingClientRect();
    const hit = getHitElement(e.clientX - rect.left, e.clientY - rect.top);
    e.currentTarget.style.cursor = hit ? 'pointer' : 'default';
  };

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (hasDraggedRef.current) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const hit = getHitElement(x, y);

    if (clickTimerRef.current) {
      window.clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }

    clickTimerRef.current = window.setTimeout(() => {
      if (hit && hit.type === 'node') {
        setSelectedNodeName(hit.data.name_norm);
        setSelectedLink(null);
      } else if (hit && hit.type === 'link') {
        setSelectedLink(hit.data);
        setSelectedNodeName(null);
      } else {
        setSelectedLink(null);
        setSelectedNodeName(null);
      }
    }, 180);
  };

  const handleCanvasDoubleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (clickTimerRef.current) {
      window.clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }

    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const hit = getHitElement(x, y);

    if (hit && hit.type === 'node') {
      setSelectedNodeName(hit.data.name_norm);
      setSelectedLink(null);
      handleNodeDoubleClick(hit.data.name_norm);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-50 overflow-hidden font-sans select-none">
      {/* 顶部控制栏 */}
      <div className="h-14 bg-white border-b border-slate-200 px-4 flex items-center justify-between z-20 shrink-0">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="font-bold text-slate-800 text-sm">知识图谱浏览</span>
          </div>

          {/* 搜索框 */}
          <div className="relative w-80">
            <div className="flex items-center bg-slate-100 border border-slate-300 rounded-lg px-2.5 py-1 focus-within:bg-white focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
              <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
              <input
                type="text"
                className="w-full bg-transparent border-none outline-hidden text-xs text-slate-800 ml-1.5 placeholder-slate-400"
                placeholder="搜索实体..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onFocus={() => setIsDropdownOpen(true)}
              />
              {(searchQuery || currentRoot) && (
                <button
                  type="button"
                  onClick={handleClearGraph}
                  className="p-0.5 hover:bg-slate-200 rounded text-slate-400 hover:text-slate-600 transition-colors cursor-pointer"
                  title="清空搜索并重置"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* 下拉候选 */}
            {isDropdownOpen && searchCandidates.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg max-h-80 overflow-y-auto z-50">
                <div className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                  {isSearching ? '正在检索...' : `候选实体 (${searchCandidates.length})`}
                </div>
                {searchCandidates.map((ent) => (
                  <div
                    key={ent.name_norm}
                    onClick={() => handleSelectCandidate(ent)}
                    className="px-3 py-2 hover:bg-blue-50 cursor-pointer flex items-center justify-between border-b border-slate-50 transition-colors"
                  >
                    <div>
                      <div className="text-xs font-semibold text-slate-800">{ent.name}</div>
                      {ent.description && (
                        <div className="text-[11px] text-slate-400 truncate max-w-[200px]">
                          {ent.description}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-mono">
                        {ent.type}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-mono">
                        {ent.degree} 关联
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 右侧控制选项 */}
        <div className="flex items-center gap-3 text-xs text-slate-600">
          <div
            className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-md px-2.5 py-1"
            title="单跳展开时按证据数量优先保留最强关联邻域（范围 1~15）"
          >
            <span className="font-medium text-slate-700 flex items-center gap-1 select-none">
              限制最大领域数
              <HelpCircle className="w-3 h-3 text-slate-400" />:
            </span>
            <input
              type="range"
              min={1}
              max={15}
              step={1}
              value={limit}
              onChange={(e) => setLimit(parseInt(e.target.value, 10))}
              className="w-20 accent-blue-600 cursor-pointer h-1.5 bg-slate-200 rounded-lg"
            />
            <span className="font-mono font-bold text-blue-600 w-4 text-center">
              {limit}
            </span>
          </div>

          <button
            onClick={handleResetBranches}
            className="flex items-center gap-1 border border-slate-300 bg-white hover:bg-slate-50 px-2.5 py-1 rounded-md text-xs text-slate-700 cursor-pointer transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            <span>收起外延</span>
          </button>
        </div>
      </div>

      {/* 主工作区：左侧画布 + 右侧证据出处抽屉 */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* 画布区域 */}
        <div
          ref={containerRef}
          className="flex-1 relative bg-white overflow-hidden"
          onClick={() => setIsDropdownOpen(false)}
        >
          <canvas
            ref={canvasRef}
            className="w-full h-full block cursor-default"
            onMouseDown={handleCanvasMouseDown}
            onMouseMove={handleCanvasMouseMove}
            onMouseUp={handleCanvasMouseUp}
            onClick={handleCanvasClick}
            onDoubleClick={handleCanvasDoubleClick}
          />

          {/* 右上角平滑非阻塞加载提示（杜绝全屏白屏遮罩闪烁） */}
          {isLoading && (
            <div className="absolute top-4 right-4 bg-white/95 border border-slate-200 shadow-md rounded-full px-3 py-1.5 flex items-center gap-2 text-xs font-semibold text-blue-600 pointer-events-none animate-in fade-in duration-150">
              <RefreshCw className="w-3.5 h-3.5 animate-spin text-blue-600" />
              <span>正在更新图谱邻域...</span>
            </div>
          )}

          {/* 空图谱与引导状态 */}
          {nodes.length === 0 && !isLoading && (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center pointer-events-auto">
              {!currentRoot && suggestedSeeds.length === 0 ? (
                <>
                  <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mb-3">
                    <Database className="w-6 h-6" />
                  </div>
                  <h4 className="font-bold text-slate-800 text-sm mb-1">
                    暂无知识图谱数据
                  </h4>
                  <p className="text-xs text-slate-400 max-w-sm">
                    当前知识库中尚未提取到实体与关系。请先在「文档与切片」中上传并解析文档。
                  </p>
                </>
              ) : currentRoot ? (
                <>
                  <div className="w-12 h-12 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mb-3">
                    <Search className="w-6 h-6" />
                  </div>
                  <h4 className="font-bold text-slate-800 text-sm mb-1">
                    未检索到「{currentRoot}」的图谱关联
                  </h4>
                  <p className="text-xs text-slate-400 max-w-sm mb-4">
                    可在上方搜索框尝试其他实体关键词{suggestedSeeds.length > 0 ? '，或直接点击以下已入库实体：' : ''}
                  </p>
                  {suggestedSeeds.length > 0 && (
                    <div className="flex flex-wrap items-center justify-center gap-2 max-w-md">
                      {suggestedSeeds.map((seed) => (
                        <button
                          key={seed.name_norm}
                          onClick={() => handleSelectCandidate(seed)}
                          className="px-3 py-1.5 rounded-lg bg-white border border-slate-200 hover:border-blue-400 hover:bg-blue-50 text-slate-700 hover:text-blue-700 text-xs font-medium cursor-pointer shadow-2xs transition-all flex items-center gap-1.5"
                        >
                          <span>{seed.name}</span>
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-100 text-slate-500 font-mono">
                            {seed.degree} 关联
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center mb-3">
                    <Layers className="w-6 h-6" />
                  </div>
                  <h4 className="font-bold text-slate-800 text-sm mb-1">
                    选择实体开始图谱探索
                  </h4>
                  <p className="text-xs text-slate-400 max-w-sm mb-4">
                    可在上方搜索框输入实体关键词，或直接点击以下已入库实体展开探索：
                  </p>
                  {suggestedSeeds.length > 0 && (
                    <div className="flex flex-wrap items-center justify-center gap-2 max-w-md">
                      {suggestedSeeds.map((seed) => (
                        <button
                          key={seed.name_norm}
                          onClick={() => handleSelectCandidate(seed)}
                          className="px-3 py-1.5 rounded-lg bg-white border border-slate-200 hover:border-blue-400 hover:bg-blue-50 text-slate-700 hover:text-blue-700 text-xs font-medium cursor-pointer shadow-2xs transition-all flex items-center gap-1.5"
                        >
                          <span>{seed.name}</span>
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-100 text-slate-500 font-mono">
                            {seed.degree} 关联
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* 右侧证据出处抽屉 */}
        <div className="w-96 bg-slate-50 border-l border-slate-200 flex flex-col overflow-hidden shrink-0 shadow-xs">
          <div className="p-4 bg-white border-b border-slate-200 shrink-0">
            <div className="flex items-center justify-between mb-1">
              <div className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                <BookOpen className="w-4 h-4 text-blue-600" />
                <span>
                  {selectedLink
                    ? '关系证据出处'
                    : selectedNodeName
                    ? '实体档案'
                    : '证据与档案抽屉'}
                </span>
              </div>
              {selectedLink && (
                <span className="text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded font-medium">
                  {selectedLink.evidence.length} 处切片证实
                </span>
              )}
            </div>
            <div className="text-[11px] text-slate-500">
              {selectedLink
                ? `${selectedLink.source} ──[${selectedLink.type}]──> ${selectedLink.target}`
                : selectedNodeName
                ? `已选中实体: ${selectedNodeName}`
                : '请点击画布中的连线查看出处切片，或双击节点展开邻居'}
            </div>
          </div>

          <div className="flex-1 p-4 overflow-y-auto space-y-3">
            {selectedLink ? (
              resolvedEvidences.length === 0 ? (
                <div className="text-center py-10 text-xs text-slate-400">
                  该关系暂无对应的文档切片证据
                </div>
              ) : (
                resolvedEvidences.map((ev, idx) => (
                  <div
                    key={`${ev.docId}_${ev.chunkIndex}_${idx}`}
                    className="bg-white border border-slate-200 rounded-lg p-3 shadow-2xs space-y-2 hover:border-blue-300 transition-colors"
                  >
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded flex items-center gap-1">
                        <FileText className="w-3 h-3" />
                        {ev.docId}
                      </span>
                      <span className="text-slate-400 font-mono">切片 #{ev.chunkIndex}</span>
                    </div>

                    <div className="text-xs text-slate-700 leading-relaxed bg-slate-50 p-2.5 rounded border-l-2 border-blue-500 font-mono">
                      {ev.loading ? (
                        <span className="text-slate-400">正在回查原始切片文本...</span>
                      ) : (
                        ev.text
                      )}
                    </div>

                    {onNavigateToChunk && (
                      <div className="flex justify-end pt-1">
                        <button
                          onClick={() =>
                            onNavigateToChunk({
                              documentId: ev.docId,
                              chunkIndex: ev.chunkIndex,
                            })
                          }
                          className="text-[11px] text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1 cursor-pointer"
                        >
                          <span>跳转文档查看原文</span>
                          <ExternalLink className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                  </div>
                ))
              )
            ) : selectedNodeName ? (() => {
              const selectedNode = nodes.find((n) => n.name_norm === selectedNodeName);
              const connectedLinks = links.filter(
                (l) => l.source === selectedNodeName || l.target === selectedNodeName
              );

              return (
                <div className="space-y-4">
                  {/* 实体基础信息卡片 */}
                  <div className="bg-white border border-slate-200 rounded-xl p-3.5 space-y-3 shadow-2xs">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="text-sm font-bold text-slate-900">
                          {selectedNode?.name || selectedNodeName}
                        </div>
                        <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                          归一标识: {selectedNodeName}
                        </div>
                      </div>
                      <span
                        className="text-[11px] px-2 py-0.5 rounded-full font-medium text-white shrink-0"
                        style={{ backgroundColor: selectedNode?.color || '#2563eb' }}
                      >
                        {selectedNode?.type || '实体'}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-100 text-[11px] font-mono">
                      <div className="bg-slate-50 p-2 rounded-lg border border-slate-200/60">
                        <span className="text-slate-400 block text-[10px]">所在层级</span>
                        <span className="font-bold text-slate-700">
                          {selectedNode?.isRoot ? '🎯 中心根实体' : `第 ${selectedNode?.depth ?? 1} 跳邻域`}
                        </span>
                      </div>
                      <div className="bg-slate-50 p-2 rounded-lg border border-slate-200/60">
                        <span className="text-slate-400 block text-[10px]">关联证据数</span>
                        <span className="font-bold text-blue-700">
                          {selectedNode?.evidence_count ?? connectedLinks.length} 条
                        </span>
                      </div>
                    </div>

                    {/* 操作按钮 */}
                    {!selectedNode?.isRoot && (
                      <div className="pt-1">
                        <button
                          onClick={() => {
                            setCurrentRoot(selectedNodeName);
                            setSearchQuery(selectedNode?.name || selectedNodeName);
                          }}
                          className="w-full py-2 px-3 rounded-lg text-xs font-semibold bg-white text-blue-700 hover:bg-blue-50 border border-blue-200 flex items-center justify-center gap-1.5 transition-colors cursor-pointer shadow-2xs"
                          title="以此实体为新圆心重置图谱"
                        >
                          <Compass className="w-3.5 h-3.5 text-blue-600" />
                          <span>以它为圆心重新聚焦</span>
                        </button>
                      </div>
                    )}
                  </div>

                  {/* 相邻关系快捷列表 */}
                  <div className="space-y-2">
                    <div className="text-[11px] font-bold text-slate-600 flex items-center justify-between px-1">
                      <span>当前可视关联关系 ({connectedLinks.length})</span>
                      <span className="text-[10px] text-slate-400">点击关系看切片出处</span>
                    </div>

                    {connectedLinks.length === 0 ? (
                      <div className="text-center py-6 text-xs text-slate-400 bg-white rounded-lg border border-slate-200">
                        暂无直接连线
                      </div>
                    ) : (
                      connectedLinks.map((link) => {
                        const isOut = link.source === selectedNodeName;
                        const other = isOut ? link.target : link.source;
                        const otherNode = nodes.find((n) => n.name_norm === other);
                        return (
                          <div
                            key={link.id}
                            onClick={() => {
                              setSelectedLink(link);
                              setSelectedNodeName(null);
                            }}
                            className="p-2.5 bg-white hover:bg-blue-50 border border-slate-200 hover:border-blue-300 rounded-xl cursor-pointer transition-all space-y-1 shadow-2xs"
                          >
                            <div className="flex items-center justify-between text-[11px]">
                              <span className="font-semibold text-blue-700">
                                {isOut ? `──[${link.type}]──>` : `<──[${link.type}]──`}
                              </span>
                              <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-mono">
                                {link.evidence.length} 条证据
                              </span>
                            </div>
                            <div className="text-xs text-slate-800 font-medium truncate">
                              {otherNode?.name || other}
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              );
            })() : (
              <div className="h-full flex flex-col items-center justify-center text-center text-slate-400 text-xs py-16 space-y-2">
                <Layers className="w-8 h-8 text-slate-300 stroke-[1.5]" />
                <p>点击任意连线查看底层证据出处</p>
                <p className="text-[11px] text-slate-400">双击节点展开或收起邻居</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
