// ASCII Animation System for Grokgates

class ASCIIAnimator {
    constructor(asciiArt) {
        this.originalLines = asciiArt.trim().split('\n');
        this.height = this.originalLines.length;
        this.width = Math.max(...this.originalLines.map(line => line.length));
        
        // Pad all lines to same width
        this.lines = this.originalLines.map(line => line.padEnd(this.width, ' '));
        
        this.animationFrame = 0;
        this.animationId = null;
        this.currentAnimation = null;
        this.fps = 20;
    }
    
    startAnimation(animationType) {
        this.stopAnimation();
        this.currentAnimation = animationType;
        this.animationFrame = 0;
        this.animate();
    }
    
    stopAnimation() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        this.currentAnimation = null;
        this.displayFrame(this.lines);
    }
    
    animate() {
        if (!this.currentAnimation) return;
        
        const startTime = performance.now();
        
        const frame = () => {
            const currentTime = performance.now();
            const deltaTime = currentTime - startTime;
            
            // Calculate frame based on time for consistent speed
            this.animationFrame = Math.floor(deltaTime / (1000 / this.fps));
            
            let animatedLines;
            switch(this.currentAnimation) {
                case 'wave':
                    animatedLines = this.waveEffect(this.animationFrame);
                    break;
                case 'pulse':
                    animatedLines = this.pulseEffect(this.animationFrame);
                    break;
                case 'bounce':
                    animatedLines = this.bounceEffect(this.animationFrame);
                    break;
                case 'shake':
                    animatedLines = this.shakeEffect(this.animationFrame);
                    break;
                case 'glitch':
                    animatedLines = this.glitchEffect(this.animationFrame);
                    break;
                case 'dance':
                    animatedLines = this.danceEffect(this.animationFrame);
                    break;
                case 'matrix':
                    animatedLines = this.matrixEffect(this.animationFrame);
                    break;
                case 'blink':
                    animatedLines = this.blinkEffect(this.animationFrame);
                    break;
                default:
                    animatedLines = this.lines;
            }
            
            this.displayFrame(animatedLines);
            this.animationId = requestAnimationFrame(frame);
        };
        
        frame();
    }
    
    displayFrame(lines) {
        const artElement = document.getElementById('ascii-art');
        if (artElement) {
            artElement.textContent = lines.join('\n');
        }
    }
    
    waveEffect(frame) {
        const animated = [];
        for (let y = 0; y < this.lines.length; y++) {
            const line = this.lines[y];
            const offset = Math.floor(Math.sin((y * 0.2) + (frame * 0.2)) * 4);
            
            let newLine;
            if (offset > 0) {
                newLine = ' '.repeat(offset) + line.slice(0, -offset);
            } else if (offset < 0) {
                newLine = line.slice(-offset) + ' '.repeat(-offset);
            } else {
                newLine = line;
            }
            
            animated.push(newLine);
        }
        return animated;
    }
    
    pulseEffect(frame) {
        const scale = 1.0 + Math.sin(frame * 0.1) * 0.1;
        const animated = [];
        
        if (scale > 1) {
            const emptyLines = Math.floor((this.height * (scale - 1)) / 2);
            for (let i = 0; i < emptyLines; i++) {
                animated.push(' '.repeat(this.width));
            }
        }
        
        for (const line of this.lines) {
            if (scale > 1) {
                let stretched = '';
                for (const char of line) {
                    stretched += char;
                    if (Math.random() < (scale - 1)) {
                        stretched += char;
                    }
                }
                animated.push(stretched.slice(0, this.width));
            } else {
                if (Math.random() > (1 - scale)) {
                    animated.push(line);
                }
            }
        }
        
        return animated;
    }
    
    bounceEffect(frame) {
        const bounceHeight = Math.abs(Math.floor(Math.sin(frame * 0.2) * 5));
        const animated = [];
        
        // Add empty lines at top
        for (let i = 0; i < bounceHeight; i++) {
            animated.push(' '.repeat(this.width));
        }
        
        // Add the image
        animated.push(...this.lines);
        
        // Return only the visible portion
        return animated.slice(0, this.height);
    }
    
    shakeEffect(frame) {
        const animated = [];
        
        // Random offset for shaking
        const shakeX = Math.floor(Math.random() * 5) - 2;
        const shakeY = Math.floor(Math.random() * 3) - 1;
        
        // Add vertical shake
        if (shakeY > 0) {
            for (let i = 0; i < shakeY; i++) {
                animated.push(' '.repeat(this.width));
            }
        }
        
        for (const line of this.lines) {
            let newLine;
            if (shakeX > 0) {
                newLine = ' '.repeat(shakeX) + line.slice(0, -shakeX);
            } else if (shakeX < 0) {
                newLine = line.slice(-shakeX) + ' '.repeat(-shakeX);
            } else {
                newLine = line;
            }
            animated.push(newLine);
        }
        
        return animated.slice(0, this.height);
    }
    
    glitchEffect(frame) {
        const animated = [];
        const glitchIntensity = Math.random();
        
        for (let y = 0; y < this.lines.length; y++) {
            const line = this.lines[y];
            
            if (Math.random() < glitchIntensity * 0.1) {
                // Glitch this line
                if (Math.random() < 0.5) {
                    // Shift line
                    const offset = Math.floor(Math.random() * 11) - 5;
                    let newLine;
                    if (offset > 0) {
                        newLine = ' '.repeat(offset) + line.slice(0, -offset);
                    } else {
                        newLine = line.slice(-offset) + ' '.repeat(-offset);
                    }
                    animated.push(newLine);
                } else {
                    // Corrupt characters
                    let newLine = '';
                    for (const char of line) {
                        if (char !== ' ' && Math.random() < 0.3) {
                            newLine += '!@#$%^&*'[Math.floor(Math.random() * 8)];
                        } else {
                            newLine += char;
                        }
                    }
                    animated.push(newLine);
                }
            } else {
                animated.push(line);
            }
        }
        
        return animated;
    }
    
    danceEffect(frame) {
        // Cycle through different moves
        const moveDuration = 20;
        const currentMove = Math.floor(frame / moveDuration) % 4;
        
        if (currentMove === 0) {
            // Sway side to side
            const offset = Math.floor(Math.sin(frame * 0.3) * 5);
            const animated = [];
            for (const line of this.lines) {
                let newLine;
                if (offset > 0) {
                    newLine = ' '.repeat(offset) + line.slice(0, -offset);
                } else {
                    newLine = line.slice(-offset) + ' '.repeat(-offset);
                }
                animated.push(newLine);
            }
            return animated;
        } else if (currentMove === 1) {
            return this.bounceEffect(frame);
        } else if (currentMove === 2) {
            return this.waveEffect(frame);
        } else {
            return this.shakeEffect(frame);
        }
    }
    
    matrixEffect(frame) {
        const animated = [];
        
        for (const line of this.lines) {
            let newLine = '';
            for (const char of line) {
                if (char !== ' ' && Math.random() < 0.05) {
                    newLine += Math.random() < 0.5 ? '0' : '1';
                } else {
                    newLine += char;
                }
            }
            animated.push(newLine);
        }
        
        return animated;
    }
    
    blinkEffect(frame) {
        const animated = [];
        const blinkOn = (frame % 30) > 5;
        
        for (const line of this.lines) {
            let newLine = '';
            for (const char of line) {
                if ('oO0@*'.includes(char) && !blinkOn) {
                    newLine += '-';
                } else {
                    newLine += char;
                }
            }
            animated.push(newLine);
        }
        
        return animated;
    }
}

// Initialize animator when DOM is loaded
let asciiAnimator = null;
let animationTimeout = null;

// Setup event listeners when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Fetch ASCII art from server
    fetch('/api/ascii-art')
        .then(response => response.json())
        .then(data => {
            if (data.ascii_art) {
                // Initialize animator with fetched ASCII art
                asciiAnimator = new ASCIIAnimator(data.ascii_art);
                asciiAnimator.displayFrame(asciiAnimator.lines);
                // Mirror initial frame to mobile container if present
                const mobileArt = document.getElementById('ascii-art-mobile');
                if (mobileArt) {
                    mobileArt.textContent = asciiAnimator.lines.join('\n');
                }
                
                // Array of animation types
                const animations = ['wave', 'pulse', 'bounce', 'shake', 'glitch', 'dance', 'matrix', 'blink'];
                
                // Function to pick and play random animation
                function randomAnimation() {
                    if (!asciiAnimator) return;
                    
                    // Pick random animation
                    const randomIndex = Math.floor(Math.random() * animations.length);
                    const animationType = animations[randomIndex];
                    
                    console.log(`▓ INITIATING ${animationType.toUpperCase()} SEQUENCE ▓`);
                    asciiAnimator.startAnimation(animationType);
                    const mobileArtEl = document.getElementById('ascii-art-mobile');
                    if (mobileArtEl) {
                        const prevDisplay = asciiAnimator.displayFrame.bind(asciiAnimator);
                        asciiAnimator.displayFrame = (lines) => {
                            prevDisplay(lines);
                            mobileArtEl.textContent = lines.join('\n');
                        };
                    }
                    
                    // Stop animation after 5-15 seconds
                    const animDuration = (Math.random() * 10 + 5) * 1000;
                    setTimeout(() => {
                        asciiAnimator.stopAnimation();
                    }, animDuration);
                    
                    // Schedule next animation (5-60 seconds) - Much more frequent!
                    const nextDelay = (Math.random() * 55 + 5) * 1000;
                    animationTimeout = setTimeout(randomAnimation, nextDelay);
                }
                
                // Start random animations after initial delay
                animationTimeout = setTimeout(randomAnimation, 3000);
                
            } else {
                console.error('Failed to load ASCII art');
                document.getElementById('ascii-art').textContent = '▓ ERROR: ASCII DATA CORRUPTED ▓';
            }
        })
        .catch(error => {
            console.error('Error fetching ASCII art:', error);
            document.getElementById('ascii-art').textContent = '▓ CONNECTION LOST ▓';
        });
});