"""One source of truth for displayed and encoded output dimensions."""
def even_size(width,height):
    if min(width,height)<2:raise ValueError('输出尺寸至少为 2×2。')
    return int(width)//2*2,int(height)//2*2


def export_size(width,height,quality):
    width,height=even_size(width,height)
    bounds={23:(1920,1080),28:(1280,720)}.get(quality)
    if bounds is None:return width,height
    if height>width:bounds=bounds[::-1]
    factor=min(1,bounds[0]/width,bounds[1]/height)
    return max(2,int(width*factor)//2*2),max(2,int(height*factor)//2*2)
