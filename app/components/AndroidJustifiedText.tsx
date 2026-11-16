import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import type { LayoutChangeEvent, TextLayoutEvent } from 'react-native';

import {
  buildJustifiedLines,
  buildLineDescriptors,
  sliceRuns,
} from '../utils/agreement_justify';
import type { JustifiedLine, JustifyRun, LineDescriptor } from '../utils/agreement_justify';

interface Props {
  runs: readonly (readonly [string, boolean])[];
  fontSize: number;
  lineHeight: number;
  color: string;
}

type Result = 'measuring' | 'second' | 'native' | JustifiedLine[];

interface JustifyState {
  key: string;
  result: Result;
  descriptors?: LineDescriptor[];
  fullWidths?: number[];
}

function renderRunSpans(runs: readonly JustifyRun[]) {
  return runs.map((run, index) => (
    <Text key={index} style={run.bold ? styles.bold : undefined}>
      {run.text}
    </Text>
  ));
}

function renderRuns(runs: readonly JustifyRun[]) {
  return <Text>{renderRunSpans(runs)}</Text>;
}

function renderJustifiedLine(line: JustifiedLine) {
  if (line.letterSpacing > 0) {
    const chars = Array.from(line.visibleText);
    const lastChar = chars[chars.length - 1];
    const headLength = line.visibleText.length - lastChar.length;
    const headRuns = sliceRuns(line.visibleRuns, 0, headLength);
    const tailRuns = [
      ...sliceRuns(line.visibleRuns, headLength, line.visibleText.length),
      ...line.trailingRuns,
    ];
    return (
      <React.Fragment>
        <Text style={{ letterSpacing: line.letterSpacing }}>{renderRunSpans(headRuns)}</Text>
        {renderRuns(tailRuns)}
      </React.Fragment>
    );
  }
  return renderRuns(line.displayRuns);
}

export function AndroidJustifiedText({ runs, fontSize, lineHeight, color }: Props) {
  const { fontScale } = useWindowDimensions();
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
  const measureKey = `${containerWidth}|${fontScale}|${fontSize}|${sourceText}|${boldSignature}`;
  const result: Result = state.key === measureKey ? state.result : 'measuring';
  const finalLines = Array.isArray(result) ? result : null;
  const descriptors = state.key === measureKey ? state.descriptors : undefined;
  const measurable = containerWidth > 0;

  useEffect(() => {
    setState({ key: measureKey, result: 'measuring' });
  }, [measureKey]);

  const handleLayout = useCallback((event: LayoutChangeEvent) => {
    const width = event.nativeEvent.layout.width;
    setContainerWidth((current) => (Math.abs(current - width) > 0.5 ? width : current));
  }, []);

  const handleFirstLayout = useCallback(
    (event: TextLayoutEvent) => {
      const measured = event.nativeEvent.lines;
      setState((current) => {
        if (current.key !== measureKey || current.result !== 'measuring') {
          return current;
        }
        if (measured.length <= 1) {
          return { key: measureKey, result: 'native' };
        }
        const nextDescriptors = buildLineDescriptors(justifyRuns, measured);
        if (!nextDescriptors) {
          return { key: measureKey, result: 'native' };
        }
        const fullWidths = measured.map((line) => line.width);
        if (nextDescriptors.some((line) => line.trailingText.length > 0)) {
          return {
            key: measureKey,
            result: 'second',
            descriptors: nextDescriptors,
            fullWidths,
          };
        }
        const nextLines = buildJustifiedLines(
          nextDescriptors,
          fullWidths,
          fullWidths,
          containerWidth,
          fontScale,
        );
        return { key: measureKey, result: nextLines ?? 'native' };
      });
    },
    [containerWidth, fontScale, justifyRuns, measureKey],
  );

  const handleSecondLayout = useCallback(
    (event: TextLayoutEvent) => {
      const measured = event.nativeEvent.lines;
      setState((current) => {
        if (
          current.key !== measureKey ||
          current.result !== 'second' ||
          !current.descriptors ||
          !current.fullWidths
        ) {
          return current;
        }
        const nextLines = buildJustifiedLines(
          current.descriptors,
          measured.map((line) => line.width),
          current.fullWidths,
          containerWidth,
          fontScale,
        );
        return { key: measureKey, result: nextLines ?? 'native' };
      });
    },
    [containerWidth, fontScale, measureKey],
  );

  const finalWidth =
    containerWidth + Math.max(0, ...(finalLines ?? []).map((line) => line.trailingWidth)) + 1;

  return (
    <View style={styles.container} onLayout={handleLayout} testID="agreement-justify-root">
      {measurable && finalLines ? (
        <Text
          testID="agreement-justify-final"
          style={[styles.final, { width: finalWidth, fontSize, lineHeight, color }]}
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

      {measurable && result === 'measuring' ? (
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

      {measurable && result === 'second' && descriptors ? (
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
                {renderRuns(line.visibleRuns)}
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
});
