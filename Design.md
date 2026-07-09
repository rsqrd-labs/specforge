---

name: Modern Indica

colors:

ink-canvas: '#f9f9f9'

ink-canvas-dim: '#dadada'

ink-canvas-bright: '#f9f9f9'

ink-panel-flat: '#ffffff'

ink-panel-soft: '#f3f3f4'

ink-panel: '#eeeeee'

ink-panel-raised: '#e8e8e8'

ink-panel-lifted: '#e2e2e2'

ink-text: '#1a1c1c'

ink-text-muted: '#554336'

ink-canvas-inverse: '#2f3131'

ink-text-inverse: '#f0f1f1'

ink-border: '#887364'

ink-border-soft: '#dbc2b0'

ink-tint: '#8f4e00'

brand-primary: '#8f4e00'

brand-primary-text: '#ffffff'

brand-primary-soft: '#ff9933'

brand-primary-soft-text: '#693800'

brand-primary-inverse: '#ffb77a'

brand-secondary: '#a1385f'

brand-secondary-text: '#ffffff'

brand-secondary-soft: '#fd80a9'

brand-secondary-soft-text: '#76143e'

brand-tertiary: '#565e74'

brand-tertiary-text: '#ffffff'

brand-tertiary-soft: '#aab1ca'

brand-tertiary-soft-text: '#3c4459'

status-error: '#ba1a1a'

status-error-text: '#ffffff'

status-error-soft: '#ffdad6'

status-error-soft-text: '#93000a'

ink-page: '#f9f9f9'

ink-page-text: '#1a1c1c'

typography:

h1:

fontFamily: Plus Jakarta Sans

fontSize: 48px

fontWeight: '700'

lineHeight: '1.2'

letterSpacing: -0.02em

h2:

fontFamily: Plus Jakarta Sans

fontSize: 36px

fontWeight: '700'

lineHeight: '1.2'

letterSpacing: -0.01em

h3:

fontFamily: Plus Jakarta Sans

fontSize: 24px

fontWeight: '600'

lineHeight: '1.3'

body-lg:

fontFamily: Plus Jakarta Sans

fontSize: 18px

fontWeight: '400'

lineHeight: '1.6'

body-md:

fontFamily: Plus Jakarta Sans

fontSize: 16px

fontWeight: '400'

lineHeight: '1.6'

label-sm:

fontFamily: Plus Jakarta Sans

fontSize: 14px

fontWeight: '600'

lineHeight: '1.2'

letterSpacing: 0.05em

rounded:

sm: 0.25rem

DEFAULT: 0.5rem

md: 0.75rem

lg: 1rem

xl: 1.5rem

full: 9999px

spacing:

unit: 8px

xs: 4px

sm: 8px

md: 16px

lg: 24px

xl: 48px

container-max: 1280px

gutter: 24px

---

  

## Brand & Style

  

This design system captures the vibrant energy and sophisticated heritage of India, translating it into a premium digital experience. The brand personality is "Modern Traditionalist"—respectful of roots but relentlessly tech-forward. It targets a discerning global audience that appreciates cultural depth paired with world-class usability.

  

The visual style is a blend of **Minimalism** and **Glassmorphism**. We use expansive white space to ground the high-energy palette, while subtle translucent layers and frosted glass effects provide a sense of atmospheric depth reminiscent of dawn light. The emotional response should be one of "Vibrant Serenity"—energetic yet balanced, professional yet warm.

  

## Colors

  

The palette is anchored by **Saffron**, representing courage and sacrifice, used primarily for calls to action and key brand moments. **Lotus Pink** serves as a sophisticated secondary accent, symbolizing purity and grace, used for highlights, tags, and celebratory UI states.

  

**Pure White** is the dominant structural color to ensure a clean, high-end feel. For text and deep structural contrast, we utilize **Deep Navy (#0F172A)** rather than pure black to maintain a premium, expansive depth that ensures maximum readability and WCAG compliance.

  

## Typography

  

We employ **Plus Jakarta Sans** for its exceptional clarity and modern geometric construction. It provides the "tech-forward" feel required while its soft curves echo the organic roundness of the overall design language.

  

Headlines use heavy weights and slight negative letter-spacing to command attention. Body text is set with generous line heights to ensure a relaxed reading rhythm. Labels use a slightly tighter, uppercase treatment to distinguish them from functional body copy.

  

## Layout & Spacing

  

The system utilizes a **Fixed Grid** model for desktop (12 columns) and a **Fluid Grid** for mobile devices. The rhythm is built on a strict 8px baseline grid to maintain mathematical harmony.

  

Margins and gutters are generous (24px+) to prevent the vibrant colors from feeling cluttered. Content blocks should be separated by significant vertical padding (48px or 64px) to emphasize the premium, "unrushed" nature of the interface.

  

## Elevation & Depth

  

Depth is conveyed through **Ambient Shadows** and **Tonal Layers**. Instead of harsh shadows, we use "Saffron-tinted" or "Navy-tinted" glows that feel like natural light dispersal.

  

1. **Level 0 (Base):** Pure White (#FFFFFF).

2. **Level 1 (Cards):** Low-opacity Saffron shadows (4% opacity, 12px blur) to make elements feel like they are floating on a warm surface.

3. **Level 2 (Overlays/Modals):** Glassmorphism with a 12px backdrop blur and a 1px semi-transparent white border.

4. **Interactive:** Elements subtly lift (increasing shadow spread) upon hover to indicate tactility.

  

## Shapes

  

The shape language follows a **Medium (ROUND_EIGHT)** philosophy. This 8px (0.5rem) base radius provides a friendly, approachable aesthetic without becoming overly playful or "bubbly."

  

- **Standard Components:** 8px radius (Buttons, Inputs).

- **Large Containers:** 16px radius (Cards, Modals).

- **Surface Accents:** Use 24px+ radius for decorative elements or images to create an organic, petal-like feel inspired by the Lotus.

  

## Components

  

### Buttons

Primary buttons use a solid Saffron fill with Deep Navy text. Secondary buttons utilize a Lotus Pink outline with a subtle 5% pink surface tint on hover. All buttons feature the 8px corner radius.

  

### Input Fields

Inputs are defined by a 1px border in a lightened Navy (15% opacity). Upon focus, the border transitions to Saffron with a soft 4px outer glow. Labels are positioned above the input in the `label-sm` style.

  

### Cards

Cards are Pure White with a 16px corner radius. They use the Level 1 Ambient Shadow. To add "Indianness," cards can feature a 4px top-border accent in either Saffron or Lotus Pink to categorize content.

  

### Chips & Tags

Chips are pill-shaped (full round) and use low-saturation versions of the primary palette (e.g., 10% Saffron fill with 100% Saffron text) for a subtle, high-end categorization system.

  

### Interactive Lists

List items should include generous 16px padding and be separated by faint dividers (Navy 5% opacity). Hover states should use a soft Lotus Pink wash (5% opacity).

  

### Specialized Accents

Incorporate "Mandala-inspired" geometric patterns as low-opacity watermarks in the background of headers or large hero sections to reinforce the cultural resonance.