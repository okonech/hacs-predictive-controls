import { parse, stringify } from 'yaml';
import { decodeEntitiesMap, decodeMap } from './decoders.ts';
import type { MapNode, PredictiveMap } from './types.ts';

/** Core + compatibility quoting protects both YAML 1.2 and HA's 1.1 loaders. */
export function dumpMapYaml(map: PredictiveMap): string {
    return stringify(map, { version: '1.2', compat: 'yaml-1.1', lineWidth: 0, directives: false });
}
export function parseMapYaml(source: string): PredictiveMap {
    const value: unknown = parse(source, { version: '1.1', maxAliasCount: 100 });
    return decodeMap(value);
}
export function formatEntities(entities: NonNullable<MapNode['entities']>): string {
    return stringify(entities, { version: '1.2', compat: 'yaml-1.1', lineWidth: 0, directives: false, collectionStyle: 'flow' }).trim();
}
export function parseEntities(source: string): NonNullable<MapNode['entities']> {
    if (!source.trim()) return {};
    const value: unknown = parse(source, { version: '1.1', maxAliasCount: 100 });
    if (typeof value === 'string') return { motion: value };
    return decodeEntitiesMap(value);
}