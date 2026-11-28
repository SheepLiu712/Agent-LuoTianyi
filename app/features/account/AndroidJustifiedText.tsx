import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import type { LayoutChangeEvent, TextLayoutEvent } from 'react-native';

import {
  buildJustifiedLines,
  buildLineDescriptors,
  sliceRuns,
  usesNativeJustification,
} from '../../utils/agreement_justify';
import type { JustifiedLine, JustifyRun, LineDescriptor } from '../../utils/agreement_justify';

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
  // Include run boundaries as well as text: a new agreement can move bold ranges
  // without changing its plain text or sequence of bold flags.
  const measureKey = JSON.stringify([containerWidth, fontScale, fontSize, runs]);
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
        if (nextDescriptors.some((line) =>
          !usesNativeJustification(line) && line.trailingText.length > 0,
        )) {
          return { key: measureKey, result: 'second', descriptors: nextDescriptors };
        }
        const nextLines = buildJustifiedLines(
          nextDescriptors,
          measured.map((line) => line.width),
          containerWidth,
          fontScale,
        );
        return {
          key: measureKey,
          result: nextLines?.some((line) => line.letterSpacing > 0) ? nextLines : 'native',
        };
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
          !current.descriptors
        ) {
          return current;
        }
        const nextLines = buildJustifiedLines(
          current.descriptors,
          measured.map((line) => line.width),
          containerWidth,
          fontScale,
        );
        return {
          key: measureKey,
          result: nextLines?.some((line) => line.letterSpacing > 0) ? nextLines : 'native',
        };
      });
    },
    [containerWidth, fontScale, measureKey],
  );

  return (
    <View style={styles.container} onLayout={handleLayout} testID="agreement-justify-root">
      {measurable && finalLines ? (
        <Text
          testID="agreement-justify-final"
          textBreakStrategy="simple"
          style={{ width: containerWidth, fontSize, lineHeight, color, textAlign: 'justify' }}
        >
          {finalLines.map((line, index) => (
            <React.Fragment key={index}>{renderJustifiedLine(line)}</React.Fragment>
          ))}
        </Text>
      ) : (
        <Text
          testID="agreement-justify-placeholder"
          textBreakStrategy="simple"
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
            textBreakStrategy="simple"
            style={{ width: containerWidth, fontSize, lineHeight, textAlign: 'justify' }}
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
            textBreakStrategy="simple"
            style={{ width: containerWidth, fontSize, lineHeight, textAlign: 'left' }}
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
  measureLayer: { position: 'absolute', left: 0, top: 0, opacity: 0 },
  bold: { fontWeight: 'bold' },
});
