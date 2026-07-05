import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  FlatList,
  Pressable,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { auth } from '../components/auth';
import {
  createDynamic,
  createDynamicComment,
  DynamicComment,
  DynamicCommentListResponse,
  DynamicPost,
  getDynamicComments,
  getDynamics,
  markDynamicsRead,
} from '../utils/dynamics';
import { addDebugTrace } from '../utils/debug_trace';
import { AppTheme, THEMES } from '../utils/theme';

interface DynamicsScreenProps {
  onClose: () => void;
  onUnreadCleared?: () => void;
  theme?: AppTheme;
}

interface CommentBucket {
  items: DynamicComment[];
  hasMore: boolean;
  nextCursor: string | null;
  loading: boolean;
  loaded: boolean;
  error: string | null;
}

function buildEmptyCommentBucket(): CommentBucket {
  return {
    items: [],
    hasMore: false,
    nextCursor: null,
    loading: false,
    loaded: false,
    error: null,
  };
}

function getAuthorTone(authorType: string, theme: AppTheme) {
  if (authorType === 'agent') {
    return { backgroundColor: theme.accentSoft, color: theme.accentText, label: '天依' };
  }
  if (authorType === 'system') {
    return { backgroundColor: theme.surfaceAlt, color: theme.textMuted, label: '系统' };
  }
  return { backgroundColor: theme.surfaceAlt, color: theme.textSoft, label: '你' };
}

function getSourceLabel(sourceType: string) {
  switch (sourceType) {
    case 'citywalk':
      return '城市漫步';
    case 'song_learned':
      return '学会新歌';
    case 'system_notice':
      return '系统通知';
    case 'user_post':
      return '生活动态';
    default:
      return sourceType || '动态';
  }
}

function getReplyStatusText(post: DynamicPost) {
  if (post.author_type !== 'user') {
    return '';
  }
  if (post.reply_status === 'pending') {
    return '天依稍后会来看';
  }
  if (post.reply_status === 'failed') {
    return '这条动态的回复生成失败了';
  }
  return '';
}

export default function DynamicsScreen({
  onClose,
  onUnreadCleared,
  theme = THEMES.light,
}: DynamicsScreenProps) {
  const insets = useSafeAreaInsets();
  const [posts, setPosts] = useState<DynamicPost[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createText, setCreateText] = useState('');
  const [expandedPostIds, setExpandedPostIds] = useState<Record<string, boolean>>({});
  const [commentStateMap, setCommentStateMap] = useState<Record<string, CommentBucket>>({});
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const [commentSubmittingMap, setCommentSubmittingMap] = useState<Record<string, boolean>>({});
  const [errorText, setErrorText] = useState('');
  const [lastHeaderTapAt, setLastHeaderTapAt] = useState(0);
  const listRef = React.useRef<FlatList<DynamicPost>>(null);

  const username = auth.username;
  const token = auth.message_token;

  const loadReadState = useCallback(async () => {
    if (!username || !token) {
      return;
    }
    try {
      const result = await markDynamicsRead(username, token);
      if (result.ok) {
        onUnreadCleared?.();
      }
    } catch (error) {
      addDebugTrace('dynamics', 'mark read failed', { error: String(error) });
    }
  }, [onUnreadCleared, token, username]);

  const loadPosts = useCallback(async (options?: { cursor?: string | null; append?: boolean; silent?: boolean }) => {
    if (!username || !token) {
      return;
    }
    const append = Boolean(options?.append);
    const cursor = options?.cursor || null;
    try {
      const result = await getDynamics(username, token, 20, cursor);
      setPosts((current) => (append ? [...current, ...result.items] : result.items));
      setHasMore(result.has_more);
      setNextCursor(result.next_cursor);
      setErrorText('');
      if (!append) {
        setExpandedPostIds({});
        setCommentStateMap({});
        await loadReadState();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '动态加载失败';
      setErrorText(message);
      if (!append) {
        setPosts([]);
      }
      throw error;
    }
  }, [loadReadState, token, username]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        await loadPosts();
      } catch {
        // loadPosts already recorded the visible error state.
      } finally {
        if (active) {
          setInitialLoading(false);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [loadPosts]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await loadPosts();
    } catch {
      // already surfaced in state
    } finally {
      setRefreshing(false);
    }
  }, [loadPosts]);

  const handleLoadMore = useCallback(async () => {
    if (!hasMore || !nextCursor || loadingMore) {
      return;
    }
    setLoadingMore(true);
    try {
      await loadPosts({ cursor: nextCursor, append: true, silent: true });
    } catch {
      // keep current list when paging fails
    } finally {
      setLoadingMore(false);
    }
  }, [hasMore, loadPosts, loadingMore, nextCursor]);

  const handleCreatePost = useCallback(async () => {
    const text = createText.trim();
    if (!username || !token) {
      Alert.alert('未登录', '当前无法发布动态');
      return;
    }
    if (!text) {
      Alert.alert('内容为空', '先写一点内容吧');
      return;
    }
    setCreateSubmitting(true);
    try {
      const created = await createDynamic(username, token, text);
      setPosts((current) => [created, ...current]);
      setCreateText('');
      setErrorText('');
    } catch (error) {
      Alert.alert('发布失败', error instanceof Error ? error.message : '动态发布失败');
    } finally {
      setCreateSubmitting(false);
    }
  }, [createText, token, username]);

  const updateCommentBucket = useCallback((dynamicId: string, updater: (current: CommentBucket) => CommentBucket) => {
    setCommentStateMap((current) => {
      const bucket = current[dynamicId] || buildEmptyCommentBucket();
      return {
        ...current,
        [dynamicId]: updater(bucket),
      };
    });
  }, []);

  const loadComments = useCallback(async (dynamicId: string, options?: { append?: boolean }) => {
    if (!username || !token) {
      return;
    }
    const append = Boolean(options?.append);
    const existing = commentStateMap[dynamicId] || buildEmptyCommentBucket();
    updateCommentBucket(dynamicId, (bucket) => ({
      ...bucket,
      loading: true,
      error: null,
    }));
    try {
      const result: DynamicCommentListResponse = await getDynamicComments(
        username,
        token,
        dynamicId,
        50,
        append ? existing.nextCursor : null,
      );
      updateCommentBucket(dynamicId, (bucket) => ({
        items: append ? [...bucket.items, ...result.items] : result.items,
        hasMore: result.has_more,
        nextCursor: result.next_cursor,
        loading: false,
        loaded: true,
        error: null,
      }));
    } catch (error) {
      updateCommentBucket(dynamicId, (bucket) => ({
        ...bucket,
        loading: false,
        loaded: true,
        error: error instanceof Error ? error.message : '评论加载失败',
      }));
    }
  }, [commentStateMap, token, updateCommentBucket, username]);

  const toggleComments = useCallback(async (dynamicId: string) => {
    const nextOpen = !expandedPostIds[dynamicId];
    setExpandedPostIds((current) => ({
      ...current,
      [dynamicId]: nextOpen,
    }));
    if (nextOpen) {
      const bucket = commentStateMap[dynamicId];
      if (!bucket?.loaded && !bucket?.loading) {
        await loadComments(dynamicId);
      }
    }
  }, [commentStateMap, expandedPostIds, loadComments]);

  const handleSubmitComment = useCallback(async (dynamicId: string) => {
    const text = (commentDrafts[dynamicId] || '').trim();
    if (!username || !token) {
      Alert.alert('未登录', '当前无法发表评论');
      return;
    }
    if (!text) {
      Alert.alert('内容为空', '先写一点评论吧');
      return;
    }
    setCommentSubmittingMap((current) => ({ ...current, [dynamicId]: true }));
    try {
      const comment = await createDynamicComment(username, token, dynamicId, text);
      updateCommentBucket(dynamicId, (bucket) => ({
        ...bucket,
        items: [...bucket.items, comment],
        loaded: true,
      }));
      setPosts((current) =>
        current.map((post) =>
          post.id === dynamicId
            ? { ...post, comment_count: (post.comment_count || 0) + 1 }
            : post,
        ),
      );
      setCommentDrafts((current) => ({ ...current, [dynamicId]: '' }));
      setExpandedPostIds((current) => ({ ...current, [dynamicId]: true }));
    } catch (error) {
      Alert.alert('评论失败', error instanceof Error ? error.message : '评论发送失败');
    } finally {
      setCommentSubmittingMap((current) => ({ ...current, [dynamicId]: false }));
    }
  }, [commentDrafts, token, updateCommentBucket, username]);

  const footer = useMemo(() => {
    if (!loadingMore) {
      if (!posts.length || hasMore) {
        return null;
      }
      return (
        <View style={styles.listFooter}>
          <Text style={[styles.footerText, { color: theme.textMuted }]}>没有更多动态了</Text>
        </View>
      );
    }
    return (
      <View style={styles.listFooter}>
        <ActivityIndicator size="small" color={theme.accent} />
      </View>
    );
  }, [hasMore, loadingMore, posts.length, theme.accent, theme.textMuted]);

  const handleHeaderTap = useCallback(() => {
    const now = Date.now();
    if (now - lastHeaderTapAt < 320) {
      listRef.current?.scrollToOffset({ offset: 0, animated: true });
      setLastHeaderTapAt(0);
      return;
    }
    setLastHeaderTapAt(now);
  }, [lastHeaderTapAt]);

  const renderCommentBlock = (post: DynamicPost) => {
    const isExpanded = Boolean(expandedPostIds[post.id]);
    const bucket = commentStateMap[post.id] || buildEmptyCommentBucket();
    const draft = commentDrafts[post.id] || '';
    const submitting = Boolean(commentSubmittingMap[post.id]);

    if (!isExpanded) {
      return null;
    }

    return (
      <View style={[styles.commentSection, { borderTopColor: theme.border }]}>
        {bucket.loading && !bucket.items.length ? (
          <View style={styles.commentLoadingRow}>
            <ActivityIndicator size="small" color={theme.accent} />
          </View>
        ) : null}

        {bucket.error ? (
          <Text style={[styles.commentErrorText, { color: theme.dangerText }]}>{bucket.error}</Text>
        ) : null}

        {!bucket.loading && !bucket.items.length ? (
          <Text style={[styles.emptyCommentText, { color: theme.textMuted }]}>还没有评论</Text>
        ) : null}

        {bucket.items.map((comment) => {
          const tone = getAuthorTone(comment.author_type, theme);
          return (
            <View key={comment.id} style={styles.commentRow}>
              <View style={styles.commentHeaderRow}>
                <View style={[styles.authorBadge, { backgroundColor: tone.backgroundColor }]}>
                  <Text style={[styles.authorBadgeText, { color: tone.color }]}>{tone.label}</Text>
                </View>
                <Text style={[styles.commentAuthorText, { color: theme.text }]}>{comment.author_name}</Text>
                <Text style={[styles.commentTimeText, { color: theme.textMuted }]}>{comment.created_at || ''}</Text>
              </View>
              <Text style={[styles.commentContentText, { color: theme.text }]}>{comment.content}</Text>
            </View>
          );
        })}

        {bucket.hasMore ? (
          <TouchableOpacity
            style={[styles.moreCommentsButton, { borderColor: theme.border, backgroundColor: theme.surfaceAlt }]}
            onPress={() => loadComments(post.id, { append: true })}
            disabled={bucket.loading}
            activeOpacity={0.8}
          >
            <Text style={[styles.moreCommentsText, { color: theme.accentText }]}>
              {bucket.loading ? '加载中...' : '加载更多评论'}
            </Text>
          </TouchableOpacity>
        ) : null}

        {post.allow_comment ? (
          <View style={styles.commentComposerRow}>
            <TextInput
              style={[
                styles.commentInput,
                {
                  backgroundColor: theme.inputBackground,
                  borderColor: theme.border,
                  color: theme.inputText,
                },
              ]}
              placeholder="写一条评论..."
              placeholderTextColor={theme.placeholder}
              value={draft}
              onChangeText={(value) => setCommentDrafts((current) => ({ ...current, [post.id]: value }))}
            />
            <TouchableOpacity
              style={[
                styles.commentSendButton,
                { backgroundColor: theme.accent },
                submitting && styles.disabledButton,
              ]}
              onPress={() => handleSubmitComment(post.id)}
              disabled={submitting}
              activeOpacity={0.82}
            >
              <Text style={[styles.commentSendButtonText, { color: theme.name === 'dark' ? '#0F1419' : '#ffffff' }]}>
                {submitting ? '发送中' : '发送'}
              </Text>
            </TouchableOpacity>
          </View>
        ) : (
          <Text style={[styles.emptyCommentText, { color: theme.textMuted }]}>系统通知暂不支持评论</Text>
        )}
      </View>
    );
  };

  const renderPost = ({ item }: { item: DynamicPost }) => {
    const tone = getAuthorTone(item.author_type, theme);
    const replyStatusText = getReplyStatusText(item);
    const commentsOpen = Boolean(expandedPostIds[item.id]);

    return (
      <View style={[styles.postCard, { backgroundColor: theme.surface, borderColor: theme.border, shadowColor: theme.shadow }]}>
        <View style={styles.postHeaderRow}>
          <View style={styles.postHeaderLeft}>
            <View style={[styles.authorBadge, { backgroundColor: tone.backgroundColor }]}>
              <Text style={[styles.authorBadgeText, { color: tone.color }]}>{tone.label}</Text>
            </View>
            <View style={styles.authorMeta}>
              <Text style={[styles.authorNameText, { color: theme.text }]}>{item.author_name}</Text>
              <Text style={[styles.sourceText, { color: theme.textMuted }]}>{getSourceLabel(item.source_type)}</Text>
            </View>
          </View>
          <Text style={[styles.timeText, { color: theme.textMuted }]}>{item.created_at || ''}</Text>
        </View>

        <Text style={[styles.postContentText, { color: theme.text }]}>{item.content}</Text>

        {replyStatusText ? (
          <Text style={[styles.replyHintText, { color: theme.textMuted }]}>{replyStatusText}</Text>
        ) : null}

        <View style={[styles.postFooterRow, { borderTopColor: theme.border }]}>
          <TouchableOpacity
            style={[styles.footerButton, { backgroundColor: theme.surfaceAlt }]}
            onPress={() => toggleComments(item.id)}
            activeOpacity={0.82}
          >
            <Text style={[styles.footerButtonText, { color: theme.accentText }]}>
              {commentsOpen ? '收起评论' : `评论 ${item.comment_count ?? 0}`}
            </Text>
          </TouchableOpacity>
        </View>

        {renderCommentBlock(item)}
      </View>
    );
  };

  if (initialLoading) {
    return (
      <View style={[styles.overlayRoot, styles.loadingRoot, { backgroundColor: theme.root }]}>
        <ActivityIndicator size="large" color={theme.accent} />
        <Text style={[styles.loadingText, { color: theme.textMuted }]}>正在加载动态...</Text>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={[styles.overlayRoot, { backgroundColor: theme.root }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.container, { paddingTop: insets.top, paddingBottom: insets.bottom, backgroundColor: theme.root }]}>
        <View style={[styles.header, { backgroundColor: theme.surface, borderBottomColor: theme.border }]}>
          <TouchableOpacity style={styles.backButton} onPress={onClose} activeOpacity={0.72}>
            <Text style={[styles.backButtonText, { color: theme.accentText }]}>返回</Text>
          </TouchableOpacity>
          <Pressable style={styles.headerTitlePressable} onPress={handleHeaderTap}>
            <Text style={[styles.headerTitle, { color: theme.text }]}>动态</Text>
          </Pressable>
          <TouchableOpacity style={styles.refreshButton} onPress={handleRefresh} activeOpacity={0.72}>
            <Text style={[styles.refreshButtonText, { color: theme.accentText }]}>刷新</Text>
          </TouchableOpacity>
        </View>

        <View style={[styles.composerPanel, { backgroundColor: theme.surface, borderBottomColor: theme.border }]}>
          <TextInput
            style={[
              styles.composerInput,
              {
                backgroundColor: theme.inputBackground,
                borderColor: theme.border,
                color: theme.inputText,
              },
            ]}
            placeholder="分享一点最近发生的事..."
            placeholderTextColor={theme.placeholder}
            value={createText}
            onChangeText={setCreateText}
            multiline
            numberOfLines={3}
            textAlignVertical="top"
          />
          <View style={styles.composerActionRow}>
            <Text style={[styles.composerHintText, { color: theme.textMuted }]}>只有你、天依和管理员能看到你的动态</Text>
            <TouchableOpacity
              style={[
                styles.publishButton,
                { backgroundColor: theme.accent },
                createSubmitting && styles.disabledButton,
              ]}
              onPress={handleCreatePost}
              disabled={createSubmitting}
              activeOpacity={0.82}
            >
              <Text style={[styles.publishButtonText, { color: theme.name === 'dark' ? '#0F1419' : '#ffffff' }]}>
                {createSubmitting ? '发布中' : '发布'}
              </Text>
            </TouchableOpacity>
          </View>
        </View>

        {errorText ? (
          <View style={[styles.errorBanner, { backgroundColor: theme.dangerSurface }]}>
            <Text style={[styles.errorBannerText, { color: theme.dangerText }]}>{errorText}</Text>
          </View>
        ) : null}

        <FlatList
          ref={listRef}
          data={posts}
          keyExtractor={(item) => item.id}
          renderItem={renderPost}
          style={styles.list}
          contentContainerStyle={styles.listContent}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor={theme.accent}
            />
          }
          onEndReached={handleLoadMore}
          onEndReachedThreshold={0.2}
          ListFooterComponent={footer}
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Text style={[styles.emptyStateText, { color: theme.textMuted }]}>这里还没有动态</Text>
            </View>
          }
          showsVerticalScrollIndicator={true}
        />
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  overlayRoot: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 130,
  },
  loadingRoot: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  loadingText: {
    fontSize: 14,
    fontWeight: '500',
  },
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  backButton: {
    minWidth: 56,
    paddingVertical: 6,
  },
  backButtonText: {
    fontSize: 16,
    fontWeight: '600',
  },
  headerTitlePressable: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    textAlign: 'center',
    fontSize: 18,
    fontWeight: '700',
  },
  refreshButton: {
    minWidth: 56,
    alignItems: 'flex-end',
    paddingVertical: 6,
  },
  refreshButtonText: {
    fontSize: 15,
    fontWeight: '600',
  },
  composerPanel: {
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 14,
    borderBottomWidth: 1,
    gap: 10,
  },
  composerInput: {
    minHeight: 92,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    fontSize: 15,
    lineHeight: 21,
  },
  composerActionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  composerHintText: {
    flex: 1,
    fontSize: 12,
    lineHeight: 18,
  },
  publishButton: {
    minWidth: 78,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  publishButtonText: {
    fontSize: 14,
    fontWeight: '700',
  },
  disabledButton: {
    opacity: 0.6,
  },
  errorBanner: {
    marginHorizontal: 16,
    marginTop: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 8,
  },
  errorBannerText: {
    fontSize: 13,
    lineHeight: 18,
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 24,
    gap: 12,
  },
  postCard: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingTop: 14,
    paddingBottom: 10,
    shadowOpacity: 0.06,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  postHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  postHeaderLeft: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minWidth: 0,
  },
  authorBadge: {
    minWidth: 38,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  authorBadgeText: {
    fontSize: 11,
    fontWeight: '700',
  },
  authorMeta: {
    flex: 1,
    minWidth: 0,
  },
  authorNameText: {
    fontSize: 15,
    fontWeight: '700',
  },
  sourceText: {
    marginTop: 2,
    fontSize: 12,
  },
  timeText: {
    maxWidth: 118,
    fontSize: 11,
    lineHeight: 16,
    textAlign: 'right',
  },
  postContentText: {
    marginTop: 12,
    fontSize: 15,
    lineHeight: 22,
  },
  replyHintText: {
    marginTop: 10,
    fontSize: 12,
    lineHeight: 18,
  },
  postFooterRow: {
    marginTop: 12,
    paddingTop: 10,
    borderTopWidth: 1,
    flexDirection: 'row',
    justifyContent: 'flex-start',
  },
  footerButton: {
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  footerButtonText: {
    fontSize: 13,
    fontWeight: '600',
  },
  commentSection: {
    marginTop: 10,
    paddingTop: 12,
    borderTopWidth: 1,
    gap: 10,
  },
  commentLoadingRow: {
    paddingVertical: 8,
    alignItems: 'center',
  },
  commentErrorText: {
    fontSize: 12,
    lineHeight: 18,
  },
  emptyCommentText: {
    fontSize: 12,
    lineHeight: 18,
  },
  commentRow: {
    gap: 6,
  },
  commentHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  commentAuthorText: {
    flex: 1,
    fontSize: 13,
    fontWeight: '600',
  },
  commentTimeText: {
    fontSize: 11,
  },
  commentContentText: {
    fontSize: 14,
    lineHeight: 20,
    paddingLeft: 2,
  },
  moreCommentsButton: {
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  moreCommentsText: {
    fontSize: 12,
    fontWeight: '600',
  },
  commentComposerRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
  },
  commentInput: {
    flex: 1,
    minHeight: 42,
    maxHeight: 96,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
  },
  commentSendButton: {
    minWidth: 68,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  commentSendButtonText: {
    fontSize: 13,
    fontWeight: '700',
  },
  listFooter: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
  },
  footerText: {
    fontSize: 12,
  },
  emptyState: {
    paddingVertical: 48,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyStateText: {
    fontSize: 14,
  },
});
