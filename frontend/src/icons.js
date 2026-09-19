/**
 * Only the icons the catalogue actually names.
 *
 * Importing the whole lucide package pulls ~800KB of unused icons into the
 * bundle, so the mapping from the catalogue's kebab-case names is explicit.
 */
import {
  BookOpen, Calculator, Calendar, ClipboardList, Clapperboard, Compass, Crosshair,
  FileText, Globe, Grid3x3, Heart, Image, Layers, Layout, Lightbulb, Mail, Map,
  Megaphone, Mic, Package, Palette, PieChart, Quote, SearchCheck, Smartphone,
  Sparkles, Target, TrendingUp, Type, Users, Video, Wind, Zap,
} from 'lucide-react'

const ICONS = {
  'book-open': BookOpen, calculator: Calculator, calendar: Calendar,
  'clipboard-list': ClipboardList, clapperboard: Clapperboard, compass: Compass,
  crosshair: Crosshair, 'file-text': FileText, globe: Globe, grid: Grid3x3,
  heart: Heart, image: Image, layers: Layers, layout: Layout, lightbulb: Lightbulb,
  mail: Mail, map: Map, megaphone: Megaphone, mic: Mic, package: Package,
  palette: Palette, 'pie-chart': PieChart, quote: Quote, 'search-check': SearchCheck,
  smartphone: Smartphone, target: Target, 'trending-up': TrendingUp, type: Type,
  users: Users, video: Video, wind: Wind, zap: Zap,
}

export const moduleIcon = (name) => ICONS[name] || Sparkles
