/**
 * Android 连续中文两端对齐（issue #313）。
 *
 * React Native 的 `textAlign: 'justify'` 在 Android 上只拉伸普通空格，
 * 连续中文的自动折行不会贴齐右边缘。本组件按 AOSP 的系统实现逐行复刻：
 *
 * 1. 第一遍测量：让系统按当前宽度自然折行，拿到每行文本；
 * 2. 按 `Layout.getLineVisibleEnd` 裁掉非末行的行尾空格，得到可见行文本；
 * 3. 仅当某个非末行确实以行尾空格结尾时，才做第二遍测量：测量裁剪后的
 *    可见行文本，得到与 AOSP `measure(end)` 对应的行宽。正常中文没有
 *    行尾空格，第一遍的行宽已经等于 `measure(end)`，跳过这一遍；
 * 4. 按 `TextLine.justify` 的 LETTER_SPACING 分支计算每行字间距，
 *    末行不参与（`Layout.isJustificationRequired` 为 false）；字间距
 *    超过 0.03px 时按 AOSP 关闭连字再做一次重测。
 *
 * 最终仍然只渲染一个外层 `Text`，行与行之间是嵌套 span + `\n`，
 * 因此行高、字体缩放、选中和读屏行为与原来的 RN Text 一致。
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  PixelRatio,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import type { LayoutChangeEvent, TextLayoutEvent } from 'react-native';

import {
  buildJustifiedLines,
  buildLineDescriptors,
  isLineEndSpace,
} from '../utils/agreement_justify';
import type { JustifiedLine, JustifyRun, LineDescriptor } from '../utils/agreement_justify';

interface Props {
  /** 已按显式换行拆好的单行 runs：[文本, 是否加粗]。 */
  runs: readonly (readonly [string, boolean])[];
  fontSize: number;
  lineHeight: number;
  color: string;
}

// native：单行或测量不可信，直接沿用系统 justify 的占位 Text。
// second：第一遍已得到折行与可见行文本，等待第二遍测量裁剪后的行宽。
// third：第二遍算出的字间距 > 0.03px，按 AOSP 关闭连字后重测。
type Result = 'measuring' | 'second' | 'third' | 'native' | JustifiedLine[];

interface JustifyState {
  key: string;
  result: Result;
  descriptors?: LineDescriptor[];
  /** third 阶段保留第二遍的临时结果，用于决定哪些行关闭连字。 */
  provisional?: JustifiedLine[];
}

function renderRuns(runs: readonly JustifyRun[]) {
  return (
    <Text>
      {runs.map((run, index) => (
        <Text key={index} style={run.bold ? styles.bold : undefined}>
          {run.text}
        </Text>
      ))}
    </Text>
  );
}

// AOSP 的行间距是整行统一应用的；这里同样给整行一个 letterSpacing，
// 不再拆分行尾字符。末行不参与 justification。
function renderJustifiedLine(line: JustifiedLine) {
  if (line.letterSpacing !== 0) {
    return (
      <Text style={{ letterSpacing: line.letterSpacing }}>
        {line.runs.map((run, index) => (
          <Text key={index} style={run.bold ? styles.bold : undefined}>
            {run.text}
          </Text>
        ))}
      </Text>
    );
  }
  return renderRuns(line.runs);
}

export function AndroidJustifiedText({ runs, fontSize, lineHeight, color }: Props) {
  const { fontScale } = useWindowDimensions();
  const density = PixelRatio.get();
  const [containerWidth, setContainerWidth] = useState(0);
  const [state, setState] = useState<JustifyState>(() => ({
    key: '',
    result: 'measuring',
  }));

  const justifyRuns = useMemo<JustifyRun[]>(
    () => runs.map(([text, bold]) => ({ text, bold })),
    [runs],
  );
  const sourceText = useMemo(() => justifyRuns.map((run) => run.text).join(''), [justifyRuns]);
  const boldSignature = useMemo(
    () => justifyRuns.map((run) => (run.bold ? '1' : '0')).join(''),
    [justifyRuns],
  );
  // 宽度、系统字号、字号、全文或粗体值变化后重新测量；lineHeight 只影响垂直布局。
  // 当前查阅页不会在组件生命周期内替换正文 runs，因此 key 不编码片段边界；
  // 若后续引入动态正文，需要把每个片段的文本和粗体边界也加入 key，否则
  // “全文相同、粗体序列相同但边界移动”会命中旧结果。
  const measureKey = `${containerWidth}|${fontScale}|${fontSize}|${sourceText}|${boldSignature}`;
  const result: Result = state.key === measureKey ? state.result : 'measuring';
  const finalLines = Array.isArray(result) ? result : null;
  const descriptors =
    state.key === measureKey && Array.isArray(state.descriptors) ? state.descriptors : null;
  const provisional =
    state.key === measureKey && Array.isArray(state.provisional) ? state.provisional : null;
  const measurable = containerWidth > 0;
  const showFinal = measurable && finalLines !== null;
  const showMeasuring = measurable && result === 'measuring';
  const showSecond = measurable && result === 'second' && descriptors !== null;
  const showThird = measurable && result === 'third' && descriptors !== null && provisional !== null;

  useEffect(() => {
    setState({ key: measureKey, result: 'measuring' });
  }, [measureKey]);

  const handleLayout = useCallback((event: LayoutChangeEvent) => {
    const width = event.nativeEvent.layout.width;
    setContainerWidth((current) => (Math.abs(current - width) > 0.5 ? width : current));
  }, []);

  // 第一遍：系统自然折行 → 按 AOSP 的可见行尾规则裁掉非末行行尾空格。
  const handleFirstLayout = useCallback(
    (event: TextLayoutEvent) => {
      const measured = event.nativeEvent.lines;
      setState((current) => {
        if (current.key !== measureKey || current.result !== 'measuring') {
          return current;
        }
        if (measured.length <= 1) {
          return { ...current, result: 'native' };
        }
        const nextDescriptors = buildLineDescriptors(justifyRuns, measured);
        if (!nextDescriptors) {
          return { ...current, result: 'native' };
        }
        // RN 对普通折行返回的宽度包含行尾空格（Layout.getLineWidth 含
        // trailing whitespace）。只有非末行真的以 AOSP 行尾空格结尾时，
        // 裁剪才会改变测量范围，才需要重测；正常中文段落没有行尾空格，
        // 第一遍宽度已经等于 AOSP measure(end) 的结果。
        const needsTrimmedWidths = measured.some(
          (line, index) =>
            index < measured.length - 1 &&
            line.text.length > 0 &&
            isLineEndSpace(line.text.charAt(line.text.length - 1)),
        );
        if (needsTrimmedWidths) {
          return { ...current, result: 'second', descriptors: nextDescriptors };
        }
        const nextLines = buildJustifiedLines(
          nextDescriptors,
          measured.map((line) => line.width * density),
          containerWidth * density,
          fontSize * fontScale * density,
          fontScale,
          density,
        );
        if (!nextLines) {
          return { ...current, result: 'native' };
        }
        // AOSP：字间距 > 0.03px 时关闭连字、重新测量并重算。
        if (nextLines.some((line) => line.ligatureDisabled)) {
          return {
            ...current,
            result: 'third',
            descriptors: nextDescriptors,
            provisional: nextLines,
          };
        }
        return { ...current, result: nextLines };
      });
    },
    [containerWidth, density, fontScale, fontSize, justifyRuns, measureKey],
  );

  // 第二遍：测量裁剪后的可见行文本，等价于 AOSP 的 measure(end)。
  const handleSecondLayout = useCallback(
    (event: TextLayoutEvent) => {
      const measured = event.nativeEvent.lines;
      setState((current) => {
        if (current.key !== measureKey || current.result !== 'second' || !current.descriptors) {
          return current;
        }
        if (measured.length !== current.descriptors.length) {
          return { ...current, result: 'native', descriptors: undefined };
        }
        const nextLines = buildJustifiedLines(
          current.descriptors,
          measured.map((line) => line.width * density),
          containerWidth * density,
          fontSize * fontScale * density,
          fontScale,
          density,
        );
        if (!nextLines) {
          return { ...current, result: 'native', descriptors: undefined };
        }
        // AOSP：字间距 > 0.03px 时关闭连字、重新测量并重算。
        if (nextLines.some((line) => line.ligatureDisabled)) {
          return { ...current, result: 'third', provisional: nextLines };
        }
        return { ...current, result: nextLines, descriptors: undefined };
      });
    },
    [containerWidth, density, fontScale, fontSize, measureKey],
  );

  // 第三遍：对命中 0.03 阈值的行关闭连字后重测，等价于 AOSP 的
  // mPaint.setFontFeatureSettings("liga" off, "cliga" off) 后 measure(end)。
  const handleThirdLayout = useCallback(
    (event: TextLayoutEvent) => {
      const measured = event.nativeEvent.lines;
      setState((current) => {
        if (
          current.key !== measureKey ||
          current.result !== 'third' ||
          !current.descriptors ||
          !current.provisional
        ) {
          return current;
        }
        if (measured.length !== current.descriptors.length) {
          return { ...current, result: 'native', descriptors: undefined, provisional: undefined };
        }
        const nextLines = buildJustifiedLines(
          current.descriptors,
          measured.map((line) => line.width * density),
          containerWidth * density,
          fontSize * fontScale * density,
          fontScale,
          density,
        );
        if (!nextLines) {
          return { ...current, result: 'native', descriptors: undefined, provisional: undefined };
        }
        return {
          ...current,
          result: nextLines,
          descriptors: undefined,
          provisional: undefined,
        };
      });
    },
    [containerWidth, density, fontScale, fontSize, measureKey],
  );

  // AOSP 在行尾也应用 paint letterSpacing，绘制宽度可能比行宽多一个间距；
  // RN 会为超宽行重新折行。给最终 Text 预留最大字间距，保持系统“行已固定、
  // 不再折行”的绘制语义。该缓冲不属于 justification 计算。
  const finalWidth = useMemo(() => {
    if (!finalLines || density <= 0) {
      return containerWidth + 1;
    }
    const maxSpacing = Math.max(
      0,
      ...finalLines.map((line) => line.spacingPx / density),
    );
    return containerWidth + maxSpacing + 1;
  }, [containerWidth, density, finalLines]);

  return (
    <View style={styles.container} onLayout={handleLayout} testID="agreement-justify-root">
      {showFinal && finalLines ? (
        <Text
          testID="agreement-justify-final"
          style={[
            styles.final,
            {
              width: finalWidth,
              fontSize,
              lineHeight,
              color,
            },
          ]}
        >
          {finalLines.map((line, index) => (
            <React.Fragment key={index}>
              {renderJustifiedLine(line)}
              {index < finalLines.length - 1 ? '\n' : null}
            </React.Fragment>
          ))}
        </Text>
      ) : (
        <Text
          testID="agreement-justify-placeholder"
          style={{ fontSize, lineHeight, color, textAlign: 'justify' }}
        >
          {renderRuns(justifyRuns)}
        </Text>
      )}

      {showMeasuring ? (
        <View
          style={[styles.measureLayer, { width: containerWidth }]}
          pointerEvents="none"
          importantForAccessibility="no-hide-descendants"
        >
          <Text
            testID="agreement-justify-measure-first"
            style={[styles.measureText, { width: containerWidth, fontSize, lineHeight }]}
            onTextLayout={handleFirstLayout}
          >
            {renderRuns(justifyRuns)}
          </Text>
        </View>
      ) : null}

      {showSecond && descriptors ? (
        <View
          style={[styles.measureLayer, { width: containerWidth }]}
          pointerEvents="none"
          importantForAccessibility="no-hide-descendants"
        >
          <Text
            testID="agreement-justify-measure-second"
            style={[styles.measureText, { width: containerWidth, fontSize, lineHeight }]}
            onTextLayout={handleSecondLayout}
          >
            {descriptors.map((line, index) => (
              <React.Fragment key={index}>
                {renderRuns(line.runs)}
                {index < descriptors.length - 1 ? '\n' : null}
              </React.Fragment>
            ))}
          </Text>
        </View>
      ) : null}

      {showThird && descriptors && provisional ? (
        <View
          style={[styles.measureLayer, { width: containerWidth }]}
          pointerEvents="none"
          importantForAccessibility="no-hide-descendants"
        >
          <Text
            testID="agreement-justify-measure-third"
            style={[styles.measureText, { width: containerWidth, fontSize, lineHeight }]}
            onTextLayout={handleThirdLayout}
          >
            {descriptors.map((line, index) => (
              <React.Fragment key={index}>
                <Text style={provisional[index]?.ligatureDisabled ? styles.noLigatures : undefined}>
                  {renderRuns(line.runs)}
                </Text>
                {index < descriptors.length - 1 ? '\n' : null}
              </React.Fragment>
            ))}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { alignSelf: 'stretch' },
  final: { textAlign: 'left' },
  measureLayer: { position: 'absolute', left: 0, top: 0, opacity: 0 },
  measureText: { textAlign: 'left' },
  bold: { fontWeight: 'bold' },
  // 对应 AOSP TextLine.justify 的 "liga" off, "cliga" off。
  noLigatures: { fontVariant: ['no-common-ligatures'] },
});
