from . import t4_error_helper          # AbstractModel — không phụ thuộc
from . import product_component
from . import product_creation_line   # comodel — phải import trước parent
from . import product_creation
from . import product_creation_summary  # SQL view phụ thuộc rel của stock.lot
from . import product_template_inherit
from . import packing_request
from . import packing_request_line
from . import stock_lot
from . import stock_move        # comodel cho stock_move_line + stock_quant
from . import stock_move_line   # related từ stock_move.t4_creation_id
from . import stock_quant       # override _get_inventory_move_values
from . import stock_picking_inherit
