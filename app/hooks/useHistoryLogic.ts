import { useCallback, useEffect, useRef, useState } from "react";
import { ChatMessage } from "../types/chat";
import type { HistoryMergeMode } from "../utils/history_merge";
import { server_config } from "../config/index";
import { getHistory } from "../utils/getHistory";
import { addDebugTrace } from "../utils/debug_trace";

export interface HistoryIdentity { username: string; characterId: string; token?: string; resetEpoch?: number; }

export function historyIdentityEquals(left: HistoryIdentity, right: HistoryIdentity): boolean {
    return left.username === right.username
        && left.characterId === right.characterId
        && left.token === right.token
        && left.resetEpoch === right.resetEpoch;
}

export function useHistoryLogic(addHistoryMessage: (messages: ChatMessage[], mode?: HistoryMergeMode) => void, identity: HistoryIdentity = { username: '', characterId: '' }) {
    const [history_start_index, setHistoryStartIndex] = useState(-1); 
    const [historyLoading, setHistoryLoading] = useState(false);
    // ref 守卫：state 更新是异步的，同一帧内多次 onEndReached 会穿透 historyLoading 检查，
    // 导致并发请求、消息重复追加。用 ref 同步拦截并发调用。
    const loadingRef = useRef(false);
    const requestGenerationRef = useRef(0);
    const loadingOwnerRef = useRef<number | null>(null);
    const loadingKindRef = useRef<'older' | 'latest' | null>(null);
    const identityRef = useRef(identity);
    identityRef.current = identity;

    useEffect(() => {
        requestGenerationRef.current += 1;
        loadingRef.current = false;
        loadingOwnerRef.current = null;
        loadingKindRef.current = null;
        setHistoryStartIndex(-1);
        setHistoryLoading(false);
    }, [identity.username, identity.characterId, identity.token, identity.resetEpoch]);

    const loadHistory = useCallback(async (
        username: string,
        token: string,
        count: number = server_config.LOAD_HISTORY_COUNT 
    ): Promise<void> => {
        // 如果正在加载或已经到头，则直接返回
        if (loadingRef.current || historyLoading || history_start_index === 0
            || (identityRef.current.username && identityRef.current.username !== username)
            || (identityRef.current.token && identityRef.current.token !== token)) {
            return;
        }

        loadingRef.current = true;
        const generation = ++requestGenerationRef.current;
        const requestIdentity = identityRef.current;
        loadingOwnerRef.current = generation;
        loadingKindRef.current = 'older';
        setHistoryLoading(true); 
        try {
            // 获取历史记录数据
            const result = await getHistory(username, token, count, history_start_index); 
            if (generation !== requestGenerationRef.current || !historyIdentityEquals(requestIdentity, identityRef.current)) return;
            setHistoryStartIndex(result.startIndex);

            if (result.messages.length > 0) {
                // 将新加载的历史消息添加到现有消息列表的末尾
                addHistoryMessage(result.messages, 'older');
            }
        } catch (error) {
            addDebugTrace('history', 'load error', { error: String(error) });
        } finally {
            if (generation === requestGenerationRef.current
                && loadingOwnerRef.current === generation
                && historyIdentityEquals(requestIdentity, identityRef.current)) {
                loadingRef.current = false;
                loadingOwnerRef.current = null;
                loadingKindRef.current = null;
                setHistoryLoading(false);
            }
        }
    }, [historyLoading, history_start_index, addHistoryMessage]); // 核心依赖项

    const refreshLatestHistory = useCallback(async (
        username: string,
        token: string,
        count: number = server_config.LOAD_HISTORY_COUNT,
    ): Promise<void> => {
        if (loadingRef.current && loadingKindRef.current !== 'latest') return;
        if ((identityRef.current.username && identityRef.current.username !== username)
            || (identityRef.current.token && identityRef.current.token !== token)) return;
        const generation = ++requestGenerationRef.current;
        const requestIdentity = identityRef.current;
        loadingOwnerRef.current = generation;
        loadingKindRef.current = 'latest';
        loadingRef.current = true;
        setHistoryLoading(true);
        try {
            const result = await getHistory(username, token, count, -1);
            if (generation !== requestGenerationRef.current || !historyIdentityEquals(requestIdentity, identityRef.current)) return;
            if (result.messages.length > 0) addHistoryMessage(result.messages, 'latest');
        } catch (error) {
            addDebugTrace('history', 'latest refresh error', { error: String(error) });
        } finally {
            if (generation === requestGenerationRef.current
                && loadingOwnerRef.current === generation
                && historyIdentityEquals(requestIdentity, identityRef.current)) {
                loadingRef.current = false;
                loadingOwnerRef.current = null;
                loadingKindRef.current = null;
                setHistoryLoading(false);
            }
        }
    }, [addHistoryMessage]);

    useEffect(() => () => { requestGenerationRef.current += 1; }, []);

    return {
        history_start_index,
        historyLoading,
        loadHistory,
        refreshLatestHistory,
    }; //
}
