import type { AssessmentCategory } from '../types/module';
import type { Tone } from './primitives';

export const CATEGORY_TONES: Record<AssessmentCategory, Tone> = {
  behavioral: 'violet',
  cognitive: 'cyan',
  personality: 'emerald',
};
